"""
Microsoft To Do workflow node implementation.
Manage tasks and task lists via Microsoft Graph API.
Uses Microsoft OAuth for authentication.

Operations:
- Task Lists: 5 operations (list, create, get, update, delete)
- Tasks: 5 operations (list, create, get, update, delete)
"""

import time
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft import MICROSOFT_TODO_SCOPES
from nodes.oauth.microsoft_oauth import is_token_expired, refresh_access_token

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


# ============================================================================
# Microsoft To Do Node Credential Schema
# ============================================================================


class MicrosoftTodoOAuthCredential(BaseModel):
    """
    OAuth credential for Microsoft To Do access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["microsoft_todo_oauth"] = Field(
        "microsoft_todo_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Microsoft"
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
        title="Microsoft Account",
        description="Email address of the connected Microsoft account",
    )

    model_config = ConfigDict(json_schema_extra={
        "title": "MicrosoftTodoOAuthCredential",
        "x-credential-type": "oauth",
        "x-oauth-provider": "microsoft",
        "x-oauth-scopes": [
            "https://graph.microsoft.com/Tasks.Read",
            "https://graph.microsoft.com/Tasks.ReadWrite",
            "https://graph.microsoft.com/User.Read",
            "offline_access",
        ],
    })


# ============================================================================
# Microsoft To Do Node Configuration Models - Task List Operations
# ============================================================================


class TodoListTaskListsConfig(BaseModel):
    """Configuration for listing all task lists"""

    operation: Literal["list_task_lists"] = Field(
        default="list_task_lists",
        title="List Task Lists",
        description="List all task lists",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_task_lists",
            "x-category": "Task List",
            "x-is-trigger": False,
            "x-display-name": "List Task Lists",
        },
    )


class TodoCreateTaskListConfig(BaseModel):
    """Configuration for creating a new task list"""

    operation: Literal["create_task_list"] = Field(
        default="create_task_list",
        title="Create Task List",
        description="Create a new task list",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_task_list",
            "x-category": "Task List",
            "x-is-trigger": False,
            "x-display-name": "Create Task List",
        },
    )
    display_name: str = Field(
        ...,
        title="List Name",
        description="Name for the new task list",
        json_schema_extra={"placeholder": "My Tasks"},
    )


class TodoGetTaskListConfig(BaseModel):
    """Configuration for getting a specific task list"""

    operation: Literal["get_task_list"] = Field(
        default="get_task_list",
        title="Get Task List",
        description="Get a specific task list",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_task_list",
            "x-category": "Task List",
            "x-is-trigger": False,
            "x-display-name": "Get Task List",
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List ID",
        description="ID of the task list to retrieve",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )


class TodoUpdateTaskListConfig(BaseModel):
    """Configuration for updating a task list"""

    operation: Literal["update_task_list"] = Field(
        default="update_task_list",
        title="Update Task List",
        description="Update a task list",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_task_list",
            "x-category": "Task List",
            "x-is-trigger": False,
            "x-display-name": "Update Task List",
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List ID",
        description="ID of the task list to update",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )
    display_name: str = Field(
        ...,
        title="New List Name",
        description="New name for the task list",
        json_schema_extra={"placeholder": "Updated List Name"},
    )


class TodoDeleteTaskListConfig(BaseModel):
    """Configuration for deleting a task list"""

    operation: Literal["delete_task_list"] = Field(
        default="delete_task_list",
        title="Delete Task List",
        description="Delete a task list",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_task_list",
            "x-category": "Task List",
            "x-is-trigger": False,
            "x-display-name": "Delete Task List",
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List ID",
        description="ID of the task list to delete",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )


# ============================================================================
# Microsoft To Do Node Configuration Models - Task Operations
# ============================================================================


class TodoListTasksConfig(BaseModel):
    """Configuration for listing tasks in a task list"""

    operation: Literal["list_tasks"] = Field(
        default="list_tasks",
        title="List Tasks",
        description="List tasks in a task list",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_tasks",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "List Tasks",
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List ID",
        description="ID of the task list to list tasks from",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )
    filter_query: Optional[str] = Field(
        None,
        title="Filter",
        description="OData filter query (e.g., 'status eq 'notStarted'', 'importance eq 'high'')",
        json_schema_extra={"placeholder": "status eq 'notStarted' (optional)"},
    )
    order_by: Optional[str] = Field(
        None,
        title="Order By",
        description="Sort order for results (e.g., 'dueDateTime/dateTime', 'createdDateTime')",
        json_schema_extra={"placeholder": "dueDateTime/dateTime (optional)"},
    )
    max_results: int = Field(
        50,
        title="Max Results",
        description="Maximum number of tasks to retrieve (1-100)",
        ge=1,
        le=100,
    )


class TodoCreateTaskConfig(BaseModel):
    """Configuration for creating a new task"""

    operation: Literal["create_task"] = Field(
        default="create_task",
        title="Create Task",
        description="Create a new task",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_task",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Create Task",
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List ID",
        description="ID of the task list to create task in",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )
    title: str = Field(
        ...,
        title="Task Title",
        description="Title of the task",
        json_schema_extra={"placeholder": "Complete project proposal"},
    )
    body: Optional[str] = Field(
        None,
        title="Task Notes",
        description="Task notes/description",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Additional details about the task (optional)",
        },
    )
    due_date_time: Optional[str] = Field(
        None,
        title="Due Date",
        description="Due date in ISO 8601 format (e.g., '2024-01-15T09:00:00Z')",
        json_schema_extra={"placeholder": "2024-01-15T09:00:00Z (optional)"},
    )
    importance: str = Field(
        "normal",
        title="Importance",
        description="Task importance level",
        json_schema_extra={
            "enum": ["low", "normal", "high"],
            "enumNames": ["Low", "Normal", "High"],
        },
    )
    status: str = Field(
        "notStarted",
        title="Status",
        description="Task status",
        json_schema_extra={
            "enum": [
                "notStarted",
                "inProgress",
                "completed",
                "waitingOnOthers",
                "deferred",
            ],
            "enumNames": [
                "Not Started",
                "In Progress",
                "Completed",
                "Waiting On Others",
                "Deferred",
            ],
        },
    )


class TodoGetTaskConfig(BaseModel):
    """Configuration for getting a specific task"""

    operation: Literal["get_task"] = Field(
        default="get_task",
        title="Get Task",
        description="Get a specific task",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_task",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Get Task",
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List ID",
        description="ID of the task list containing the task",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )
    task_id: str = Field(
        ...,
        title="Task ID",
        description="ID of the task to retrieve",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )


class TodoUpdateTaskConfig(BaseModel):
    """Configuration for updating a task"""

    operation: Literal["update_task"] = Field(
        default="update_task",
        title="Update Task",
        description="Update a task",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_task",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Update Task",
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List ID",
        description="ID of the task list containing the task",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )
    task_id: str = Field(
        ...,
        title="Task ID",
        description="ID of the task to update",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )
    title: Optional[str] = Field(
        None,
        title="Task Title",
        description="New title for the task (leave empty to keep current)",
        json_schema_extra={"placeholder": "Updated task title (optional)"},
    )
    body: Optional[str] = Field(
        None,
        title="Task Notes",
        description="New task notes/description (leave empty to keep current)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Updated task notes (optional)",
        },
    )
    due_date_time: Optional[str] = Field(
        None,
        title="Due Date",
        description="New due date in ISO 8601 format (leave empty to keep current)",
        json_schema_extra={"placeholder": "2024-01-15T09:00:00Z (optional)"},
    )
    importance: Optional[str] = Field(
        None,
        title="Importance",
        description="New importance level (leave empty to keep current)",
        json_schema_extra={
            "enum": ["low", "normal", "high"],
            "enumNames": ["Low", "Normal", "High"],
            "x-enum-searchable": True,
        },
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="New task status (leave empty to keep current)",
        json_schema_extra={
            "enum": [
                "notStarted",
                "inProgress",
                "completed",
                "waitingOnOthers",
                "deferred",
            ],
            "enumNames": [
                "Not Started",
                "In Progress",
                "Completed",
                "Waiting On Others",
                "Deferred",
            ],
            "x-enum-searchable": True,
        },
    )


class TodoDeleteTaskConfig(BaseModel):
    """Configuration for deleting a task"""

    operation: Literal["delete_task"] = Field(
        default="delete_task",
        title="Delete Task",
        description="Delete a task",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_task",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Delete Task",
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List ID",
        description="ID of the task list containing the task",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )
    task_id: str = Field(
        ...,
        title="Task ID",
        description="ID of the task to delete",
        json_schema_extra={"placeholder": "AAMkAGI2..."},
    )


# ============================================================================
# Configuration Union Type
# ============================================================================

TodoConfig = Annotated[
    Union[
        # Task List operations
        TodoListTaskListsConfig,
        TodoCreateTaskListConfig,
        TodoGetTaskListConfig,
        TodoUpdateTaskListConfig,
        TodoDeleteTaskListConfig,
        # Task operations
        TodoListTasksConfig,
        TodoCreateTaskConfig,
        TodoGetTaskConfig,
        TodoUpdateTaskConfig,
        TodoDeleteTaskConfig,
    ],
    Discriminator("operation"),
]


class MicrosoftTodoNodeConfig(NodeConfig[TodoConfig, MicrosoftTodoOAuthCredential]):
    """Full configuration for Microsoft To Do node including credentials"""

    pass


# ============================================================================
# Microsoft To Do Node Implementation
# ============================================================================


class MicrosoftTodoNode(WorkflowNode):
    """
    Microsoft To Do workflow node for managing tasks and task lists.
    Uses Microsoft Graph API for all operations.
    """

    edit_examples = [
        'Create a task list named "Sprint Planning" for team coordination',
        'Add a high priority task "Review Q4 metrics" due tomorrow at 9 AM',
        'Mark all completed tasks in "In Progress" list as done',
        'List all tasks from "Personal" list that are overdue',
        "Update task status to completed and add notes about the solution",
        'Create subtasks for the "Website Redesign" project milestone',
        'Delete the archived "Old Project" task list',
    ]

    #: OAuth scope requirements per operation (nodes/scopes/microsoft.py).
    scope_registry = MICROSOFT_TODO_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_task_lists",
        noun="task lists",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Microsoft To Do node"""
        return MicrosoftTodoNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Microsoft To Do operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict containing Microsoft To Do operation results
        """
        logger.info(f"[MicrosoftTodoNode] Executing node {self.node_id}")
        start_time = time.time()

        # Get config - required for this node
        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[MicrosoftTodoNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, MicrosoftTodoNodeConfig):
            raise ValueError(
                f"[MicrosoftTodoNode] Invalid config type: {type(node_config)}, expected MicrosoftTodoNodeConfig"
            )

        # Extract the actual config and credentials
        config = node_config.config
        credentials = node_config.credentials

        # Validate credentials are provided
        if not credentials:
            raise ValueError(
                f"[MicrosoftTodoNode] Microsoft credentials are required but not provided. "
                f"Please connect a Microsoft account in the node's credentials tab."
            )

        # Ensure token is fresh before making API calls
        access_token = await self._ensure_fresh_token(credentials)

        # Execute operation based on config type
        # Task List operations
        if isinstance(config, TodoListTaskListsConfig):
            output = await self._list_task_lists(config, access_token)
        elif isinstance(config, TodoCreateTaskListConfig):
            output = await self._create_task_list(config, access_token)
        elif isinstance(config, TodoGetTaskListConfig):
            output = await self._get_task_list(config, access_token)
        elif isinstance(config, TodoUpdateTaskListConfig):
            output = await self._update_task_list(config, access_token)
        elif isinstance(config, TodoDeleteTaskListConfig):
            output = await self._delete_task_list(config, access_token)
        # Task operations
        elif isinstance(config, TodoListTasksConfig):
            output = await self._list_tasks(config, access_token)
        elif isinstance(config, TodoCreateTaskConfig):
            output = await self._create_task(config, access_token)
        elif isinstance(config, TodoGetTaskConfig):
            output = await self._get_task(config, access_token)
        elif isinstance(config, TodoUpdateTaskConfig):
            output = await self._update_task(config, access_token)
        elif isinstance(config, TodoDeleteTaskConfig):
            output = await self._delete_task(config, access_token)
        else:
            raise ValueError(
                f"[MicrosoftTodoNode] Unknown operation config type: {type(config)}"
            )

        execution_time = time.time() - start_time
        logger.info(f"[MicrosoftTodoNode] Execution completed in {execution_time:.2f}s")

        return output

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="microsoft",
        )

    async def _ensure_fresh_token(
        self, credentials: MicrosoftTodoOAuthCredential
    ) -> str:
        """Return a valid Microsoft To Do access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="microsoft",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    def _resolve_template(self, template: str, inputs: Dict[str, Any]) -> str:
        """
        Resolve template variables in a string using upstream node outputs.

        Args:
            template: String that may contain {{node_id.field}} references
            inputs: Dict of upstream node outputs

        Returns:
            Resolved string with variables replaced
        """
        if not template:
            return template

        resolved = template
        for node_id, node_output in inputs.items():
            if isinstance(node_output, dict):
                for field, value in node_output.items():
                    placeholder = f"{{{{{node_id}.{field}}}}}"
                    if placeholder in resolved:
                        resolved = resolved.replace(placeholder, str(value))

        return resolved

    # ========================================================================
    # Task List Operations
    # ========================================================================

    async def _list_task_lists(
        self, config: TodoListTaskListsConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        List all task lists via Microsoft Graph API.

        Args:
            config: List task lists configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the task list data
        """
        logger.info(f"[MicrosoftTodoNode] Listing all task lists")

        url = f"{GRAPH_API_BASE}/me/todo/lists"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[MicrosoftTodoNode] List task lists failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            data = response.json()
            task_lists = data.get("value", [])

            logger.info(f"[MicrosoftTodoNode] Retrieved {len(task_lists)} task lists")

            return {
                "type": "microsoft_todo",
                "operation": "list_task_lists",
                "status": "success",
                "task_lists": task_lists,
                "count": len(task_lists),
            }

    async def _create_task_list(
        self, config: TodoCreateTaskListConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Create a new task list via Microsoft Graph API.

        Args:
            config: Create task list configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the created task list data
        """
        logger.info(f"[MicrosoftTodoNode] Creating task list: {config.display_name}")

        url = f"{GRAPH_API_BASE}/me/todo/lists"

        payload = {"displayName": config.display_name}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code not in [200, 201]:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[MicrosoftTodoNode] Create task list failed: {error_msg}"
                )
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            task_list = response.json()

            logger.info(
                f"[MicrosoftTodoNode] Task list created with ID: {task_list.get('id')}"
            )

            return {
                "type": "microsoft_todo",
                "operation": "create_task_list",
                "status": "success",
                "task_list": task_list,
                "task_list_id": task_list.get("id"),
                "display_name": task_list.get("displayName"),
            }

    async def _get_task_list(
        self, config: TodoGetTaskListConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Get a specific task list via Microsoft Graph API.

        Args:
            config: Get task list configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the task list data
        """
        logger.info(f"[MicrosoftTodoNode] Getting task list: {config.task_list_id}")

        url = f"{GRAPH_API_BASE}/me/todo/lists/{config.task_list_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[MicrosoftTodoNode] Get task list failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            task_list = response.json()

            logger.info(
                f"[MicrosoftTodoNode] Retrieved task list: {task_list.get('displayName')}"
            )

            return {
                "type": "microsoft_todo",
                "operation": "get_task_list",
                "status": "success",
                "task_list": task_list,
                "task_list_id": task_list.get("id"),
                "display_name": task_list.get("displayName"),
            }

    async def _update_task_list(
        self, config: TodoUpdateTaskListConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Update a task list via Microsoft Graph API.

        Args:
            config: Update task list configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the updated task list data
        """
        logger.info(f"[MicrosoftTodoNode] Updating task list: {config.task_list_id}")

        url = f"{GRAPH_API_BASE}/me/todo/lists/{config.task_list_id}"

        payload = {"displayName": config.display_name}

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[MicrosoftTodoNode] Update task list failed: {error_msg}"
                )
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            task_list = response.json()

            logger.info(
                f"[MicrosoftTodoNode] Task list updated: {task_list.get('displayName')}"
            )

            return {
                "type": "microsoft_todo",
                "operation": "update_task_list",
                "status": "success",
                "task_list": task_list,
                "task_list_id": task_list.get("id"),
                "display_name": task_list.get("displayName"),
            }

    async def _delete_task_list(
        self, config: TodoDeleteTaskListConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Delete a task list via Microsoft Graph API.

        Args:
            config: Delete task list configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the deletion status
        """
        logger.info(f"[MicrosoftTodoNode] Deleting task list: {config.task_list_id}")

        url = f"{GRAPH_API_BASE}/me/todo/lists/{config.task_list_id}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 204:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[MicrosoftTodoNode] Delete task list failed: {error_msg}"
                )
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            logger.info(f"[MicrosoftTodoNode] Task list deleted successfully")

            return {
                "type": "microsoft_todo",
                "operation": "delete_task_list",
                "status": "success",
                "task_list_id": config.task_list_id,
                "message": "Task list deleted successfully",
            }

    # ========================================================================
    # Task Operations
    # ========================================================================

    async def _list_tasks(
        self, config: TodoListTasksConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        List tasks in a task list via Microsoft Graph API.

        Args:
            config: List tasks configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the tasks data
        """
        logger.info(
            f"[MicrosoftTodoNode] Listing tasks in task list: {config.task_list_id}"
        )

        url = f"{GRAPH_API_BASE}/me/todo/lists/{config.task_list_id}/tasks"

        params = {"$top": config.max_results}

        if config.filter_query:
            params["$filter"] = config.filter_query

        if config.order_by:
            params["$orderby"] = config.order_by

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[MicrosoftTodoNode] List tasks failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            data = response.json()
            tasks = data.get("value", [])

            logger.info(f"[MicrosoftTodoNode] Retrieved {len(tasks)} tasks")

            return {
                "type": "microsoft_todo",
                "operation": "list_tasks",
                "status": "success",
                "tasks": tasks,
                "count": len(tasks),
                "task_list_id": config.task_list_id,
            }

    async def _create_task(
        self, config: TodoCreateTaskConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Create a new task via Microsoft Graph API.

        Args:
            config: Create task configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the created task data
        """
        logger.info(f"[MicrosoftTodoNode] Creating task: {config.title}")

        url = f"{GRAPH_API_BASE}/me/todo/lists/{config.task_list_id}/tasks"

        # Build task payload
        payload = {
            "title": config.title,
            "importance": config.importance,
            "status": config.status,
        }

        # Add optional fields
        if config.body:
            payload["body"] = {"content": config.body, "contentType": "text"}

        if config.due_date_time:
            # Parse the datetime to ensure it's in proper format
            payload["dueDateTime"] = {
                "dateTime": config.due_date_time.replace("Z", ""),
                "timeZone": "UTC",
            }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code not in [200, 201]:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[MicrosoftTodoNode] Create task failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            task = response.json()

            logger.info(f"[MicrosoftTodoNode] Task created with ID: {task.get('id')}")

            return {
                "type": "microsoft_todo",
                "operation": "create_task",
                "status": "success",
                "task": task,
                "task_id": task.get("id"),
                "title": task.get("title"),
                "task_list_id": config.task_list_id,
            }

    async def _get_task(
        self, config: TodoGetTaskConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Get a specific task via Microsoft Graph API.

        Args:
            config: Get task configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the task data
        """
        logger.info(f"[MicrosoftTodoNode] Getting task: {config.task_id}")

        url = f"{GRAPH_API_BASE}/me/todo/lists/{config.task_list_id}/tasks/{config.task_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[MicrosoftTodoNode] Get task failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            task = response.json()

            logger.info(f"[MicrosoftTodoNode] Retrieved task: {task.get('title')}")

            return {
                "type": "microsoft_todo",
                "operation": "get_task",
                "status": "success",
                "task": task,
                "task_id": task.get("id"),
                "title": task.get("title"),
                "task_list_id": config.task_list_id,
            }

    async def _update_task(
        self, config: TodoUpdateTaskConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Update a task via Microsoft Graph API.

        Args:
            config: Update task configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the updated task data
        """
        logger.info(f"[MicrosoftTodoNode] Updating task: {config.task_id}")

        url = f"{GRAPH_API_BASE}/me/todo/lists/{config.task_list_id}/tasks/{config.task_id}"

        # Build update payload with only provided fields
        payload = {}

        if config.title:
            payload["title"] = config.title

        if config.body is not None:
            payload["body"] = {"content": config.body, "contentType": "text"}

        if config.due_date_time:
            payload["dueDateTime"] = {
                "dateTime": config.due_date_time.replace("Z", ""),
                "timeZone": "UTC",
            }

        if config.importance:
            payload["importance"] = config.importance

        if config.status:
            payload["status"] = config.status

        if not payload:
            logger.warning(
                f"[MicrosoftTodoNode] No fields to update for task {config.task_id}"
            )
            raise ValueError("At least one field must be provided to update the task")

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[MicrosoftTodoNode] Update task failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            task = response.json()

            logger.info(f"[MicrosoftTodoNode] Task updated: {task.get('title')}")

            return {
                "type": "microsoft_todo",
                "operation": "update_task",
                "status": "success",
                "task": task,
                "task_id": task.get("id"),
                "title": task.get("title"),
                "task_list_id": config.task_list_id,
            }

    async def _delete_task(
        self, config: TodoDeleteTaskConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Delete a task via Microsoft Graph API.

        Args:
            config: Delete task configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the deletion status
        """
        logger.info(f"[MicrosoftTodoNode] Deleting task: {config.task_id}")

        url = f"{GRAPH_API_BASE}/me/todo/lists/{config.task_list_id}/tasks/{config.task_id}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 204:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[MicrosoftTodoNode] Delete task failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            logger.info(f"[MicrosoftTodoNode] Task deleted successfully")

            return {
                "type": "microsoft_todo",
                "operation": "delete_task",
                "status": "success",
                "task_id": config.task_id,
                "task_list_id": config.task_list_id,
                "message": "Task deleted successfully",
            }
