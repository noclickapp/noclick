"""
Mock tests for Microsoft To Do workflow node.

Tests all 10 Microsoft To Do operations with mocked Microsoft Graph API responses.
Does not require actual Microsoft OAuth credentials.

Operations covered:
- Task Lists: 5 operations (list, create, get, update, delete)
- Tasks: 5 operations (list, create, get, update, delete)
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# Import the node and config classes - ALL 10 operations
from nodes.microsoft_todo_node import (
    MicrosoftTodoNode,
    MicrosoftTodoNodeConfig,
    MicrosoftTodoOAuthCredential,
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
)


# Mock credential data
MOCK_CREDENTIALS = MicrosoftTodoOAuthCredential(
    access_token="mock_access_token_12345",
    refresh_token="mock_refresh_token_67890",
    expires_at="2099-12-31T23:59:59Z",
    email="test@outlook.com"
)


def create_node(config) -> MicrosoftTodoNode:
    """Create a MicrosoftTodoNode instance with mock credentials."""
    node_config = MicrosoftTodoNodeConfig(config=config, credentials=MOCK_CREDENTIALS)
    node = MicrosoftTodoNode(
        node_id="test-todo-node",
        node_type="automation-microsoft-todo",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow"
    )
    return node


def create_mock_response(status_code: int, json_data: dict = None, content: bytes = None):
    """Create a mock httpx response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.content = content or b'{"success": true}'
    mock_response.json.return_value = json_data or {}
    mock_response.text = str(json_data) if json_data else ""
    return mock_response


# ============================================================================
# Task List Operations Tests
# ============================================================================

class TestTaskListOperations:
    """Test task list CRUD operations."""

    @pytest.mark.asyncio
    async def test_list_task_lists_success(self):
        """Test successfully listing all task lists."""
        config = TodoListTaskListsConfig()
        node = create_node(config)

        mock_response = create_mock_response(200, {
            "value": [
                {
                    "id": "AAMkAGI2TG93AAA=",
                    "displayName": "Tasks",
                    "isOwner": True,
                    "isShared": False,
                    "wellknownListName": "defaultList"
                },
                {
                    "id": "AAMkAGI2TG94AAA=",
                    "displayName": "My Custom List",
                    "isOwner": True,
                    "isShared": False,
                    "wellknownListName": "none"
                }
            ]
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["type"] == "microsoft_todo"
        assert result["operation"] == "list_task_lists"
        assert result["status"] == "success"
        assert result["count"] == 2
        assert len(result["task_lists"]) == 2
        assert result["task_lists"][0]["displayName"] == "Tasks"
        assert result["task_lists"][1]["displayName"] == "My Custom List"

    @pytest.mark.asyncio
    async def test_list_task_lists_error(self):
        """Test error handling when listing task lists fails."""
        config = TodoListTaskListsConfig()
        node = create_node(config)

        mock_response = create_mock_response(401, {
            "error": {"message": "Access token expired"}
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_create_task_list_success(self):
        """Test successfully creating a new task list."""
        config = TodoCreateTaskListConfig(display_name="My Tasks")
        node = create_node(config)

        mock_response = create_mock_response(201, {
            "id": "AAMkAGI2TG95AAA=",
            "displayName": "My Tasks",
            "isOwner": True,
            "isShared": False,
            "wellknownListName": "none"
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["type"] == "microsoft_todo"
        assert result["operation"] == "create_task_list"
        assert result["status"] == "success"
        assert result["task_list_id"] == "AAMkAGI2TG95AAA="
        assert result["display_name"] == "My Tasks"

    @pytest.mark.asyncio
    async def test_create_task_list_error(self):
        """Test error handling when creating task list fails."""
        config = TodoCreateTaskListConfig(display_name="My Tasks")
        node = create_node(config)

        mock_response = create_mock_response(400, {
            "error": {"message": "Invalid request"}
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_get_task_list_success(self):
        """Test successfully getting a specific task list."""
        config = TodoGetTaskListConfig(task_list_id="AAMkAGI2TG95AAA=")
        node = create_node(config)

        mock_response = create_mock_response(200, {
            "id": "AAMkAGI2TG95AAA=",
            "displayName": "My Tasks",
            "isOwner": True,
            "isShared": False,
            "wellknownListName": "none"
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["type"] == "microsoft_todo"
        assert result["operation"] == "get_task_list"
        assert result["status"] == "success"
        assert result["task_list_id"] == "AAMkAGI2TG95AAA="
        assert result["display_name"] == "My Tasks"

    @pytest.mark.asyncio
    async def test_get_task_list_not_found(self):
        """Test error handling when task list is not found."""
        config = TodoGetTaskListConfig(task_list_id="nonexistent-id")
        node = create_node(config)

        mock_response = create_mock_response(404, {
            "error": {"message": "Task list not found"}
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_update_task_list_success(self):
        """Test successfully updating a task list."""
        config = TodoUpdateTaskListConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            display_name="Updated List Name"
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {
            "id": "AAMkAGI2TG95AAA=",
            "displayName": "Updated List Name",
            "isOwner": True,
            "isShared": False
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["type"] == "microsoft_todo"
        assert result["operation"] == "update_task_list"
        assert result["status"] == "success"
        assert result["display_name"] == "Updated List Name"

    @pytest.mark.asyncio
    async def test_delete_task_list_success(self):
        """Test successfully deleting a task list."""
        config = TodoDeleteTaskListConfig(task_list_id="AAMkAGI2TG95AAA=")
        node = create_node(config)

        mock_response = create_mock_response(204, {})

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.delete = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["type"] == "microsoft_todo"
        assert result["operation"] == "delete_task_list"
        assert result["status"] == "success"
        assert result["task_list_id"] == "AAMkAGI2TG95AAA="
        assert "deleted successfully" in result["message"]


# ============================================================================
# Task Operations Tests
# ============================================================================

class TestTaskOperations:
    """Test task CRUD operations."""

    @pytest.mark.asyncio
    async def test_list_tasks_success(self):
        """Test successfully listing tasks in a task list."""
        config = TodoListTasksConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            max_results=50
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {
            "value": [
                {
                    "id": "AAkALgAAAAAAHYQDEapmEc2byACqAC",
                    "title": "Complete project proposal",
                    "status": "notStarted",
                    "importance": "high",
                    "createdDateTime": "2024-01-15T10:00:00Z",
                    "lastModifiedDateTime": "2024-01-15T10:00:00Z",
                    "body": {
                        "content": "Need to finish the Q1 proposal",
                        "contentType": "text"
                    },
                    "dueDateTime": {
                        "dateTime": "2024-01-20T17:00:00.0000000",
                        "timeZone": "UTC"
                    }
                },
                {
                    "id": "AAkALgAAAAAAHYQDEapmEc2byACqAD",
                    "title": "Review team feedback",
                    "status": "inProgress",
                    "importance": "normal",
                    "createdDateTime": "2024-01-14T09:00:00Z",
                    "lastModifiedDateTime": "2024-01-15T14:00:00Z"
                }
            ]
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["type"] == "microsoft_todo"
        assert result["operation"] == "list_tasks"
        assert result["status"] == "success"
        assert result["count"] == 2
        assert len(result["tasks"]) == 2
        assert result["tasks"][0]["title"] == "Complete project proposal"
        assert result["tasks"][0]["importance"] == "high"
        assert result["tasks"][1]["title"] == "Review team feedback"

    @pytest.mark.asyncio
    async def test_list_tasks_with_filter(self):
        """Test listing tasks with a filter query."""
        config = TodoListTasksConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            filter_query="status eq 'notStarted'",
            max_results=20
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {
            "value": [
                {
                    "id": "task-1",
                    "title": "Task 1",
                    "status": "notStarted"
                }
            ]
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_list_tasks_with_ordering(self):
        """Test listing tasks with custom ordering."""
        config = TodoListTasksConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            order_by="dueDateTime/dateTime",
            max_results=50
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {"value": []})

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_create_task_success(self):
        """Test successfully creating a new task."""
        config = TodoCreateTaskConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            title="Complete project proposal",
            body="Need to finish the Q1 proposal",
            due_date_time="2024-01-20T17:00:00Z",
            importance="high",
            status="notStarted"
        )
        node = create_node(config)

        mock_response = create_mock_response(201, {
            "id": "AAkALgAAAAAAHYQDEapmEc2byACqAC",
            "title": "Complete project proposal",
            "status": "notStarted",
            "importance": "high",
            "body": {
                "content": "Need to finish the Q1 proposal",
                "contentType": "text"
            },
            "dueDateTime": {
                "dateTime": "2024-01-20T17:00:00.0000000",
                "timeZone": "UTC"
            }
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["type"] == "microsoft_todo"
        assert result["operation"] == "create_task"
        assert result["status"] == "success"
        assert result["task_id"] == "AAkALgAAAAAAHYQDEapmEc2byACqAC"
        assert result["title"] == "Complete project proposal"

    @pytest.mark.asyncio
    async def test_create_task_minimal(self):
        """Test creating a task with only required fields."""
        config = TodoCreateTaskConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            title="Simple task"
        )
        node = create_node(config)

        mock_response = create_mock_response(201, {
            "id": "task-simple",
            "title": "Simple task",
            "status": "notStarted",
            "importance": "normal"
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["title"] == "Simple task"

    @pytest.mark.asyncio
    async def test_get_task_success(self):
        """Test successfully getting a specific task."""
        config = TodoGetTaskConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            task_id="AAkALgAAAAAAHYQDEapmEc2byACqAC"
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {
            "id": "AAkALgAAAAAAHYQDEapmEc2byACqAC",
            "title": "Complete project proposal",
            "status": "notStarted",
            "importance": "high",
            "body": {
                "content": "Need to finish the Q1 proposal",
                "contentType": "text"
            }
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["type"] == "microsoft_todo"
        assert result["operation"] == "get_task"
        assert result["status"] == "success"
        assert result["task_id"] == "AAkALgAAAAAAHYQDEapmEc2byACqAC"
        assert result["title"] == "Complete project proposal"

    @pytest.mark.asyncio
    async def test_get_task_not_found(self):
        """Test error handling when task is not found."""
        config = TodoGetTaskConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            task_id="nonexistent-task"
        )
        node = create_node(config)

        mock_response = create_mock_response(404, {
            "error": {"message": "Task not found"}
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_update_task_success(self):
        """Test successfully updating a task."""
        config = TodoUpdateTaskConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            task_id="AAkALgAAAAAAHYQDEapmEc2byACqAC",
            title="Updated task title",
            status="completed",
            importance="normal"
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {
            "id": "AAkALgAAAAAAHYQDEapmEc2byACqAC",
            "title": "Updated task title",
            "status": "completed",
            "importance": "normal"
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["type"] == "microsoft_todo"
        assert result["operation"] == "update_task"
        assert result["status"] == "success"
        assert result["title"] == "Updated task title"

    @pytest.mark.asyncio
    async def test_update_task_partial(self):
        """Test updating only some fields of a task."""
        config = TodoUpdateTaskConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            task_id="task-1",
            status="inProgress"
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {
            "id": "task-1",
            "title": "Original title",
            "status": "inProgress"
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_task_no_fields_error(self):
        """Test error when no fields are provided for update."""
        config = TodoUpdateTaskConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            task_id="task-1"
        )
        node = create_node(config)

        with pytest.raises(ValueError, match="At least one field must be provided"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_delete_task_success(self):
        """Test successfully deleting a task."""
        config = TodoDeleteTaskConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            task_id="AAkALgAAAAAAHYQDEapmEc2byACqAC"
        )
        node = create_node(config)

        mock_response = create_mock_response(204, {})

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.delete = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["type"] == "microsoft_todo"
        assert result["operation"] == "delete_task"
        assert result["status"] == "success"
        assert result["task_id"] == "AAkALgAAAAAAHYQDEapmEc2byACqAC"
        assert "deleted successfully" in result["message"]


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = TodoListTaskListsConfig()
        node_config = MicrosoftTodoNodeConfig(config=config, credentials=None)
        node = MicrosoftTodoNode(
            node_id="test-node",
            node_type="automation-microsoft-todo",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow"
        )

        with pytest.raises(ValueError, match="credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_api_401_unauthorized(self):
        """Test handling of 401 unauthorized error."""
        config = TodoListTaskListsConfig()
        node = create_node(config)

        mock_response = create_mock_response(401, {
            "error": {"message": "Access token has expired"}
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_api_404_not_found(self):
        """Test handling of 404 not found error."""
        config = TodoGetTaskListConfig(task_list_id="nonexistent-list")
        node = create_node(config)

        mock_response = create_mock_response(404, {
            "error": {"message": "Resource not found"}
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_api_400_bad_request(self):
        """Test handling of 400 bad request error."""
        config = TodoCreateTaskListConfig(display_name="")
        node = create_node(config)

        mock_response = create_mock_response(400, {
            "error": {"message": "Invalid request: displayName cannot be empty"}
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})


# ============================================================================
# Template Resolution Tests
# ============================================================================

class TestTemplateResolution:
    """Test template variable resolution in inputs."""

    @pytest.mark.asyncio
    async def test_template_in_task_title(self):
        """Test template resolution in task title field."""
        config = TodoCreateTaskConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            title="Complete {{input.prev_node.task_name}}"
        )
        node = create_node(config)

        mock_response = create_mock_response(201, {
            "id": "task-new",
            "title": "Complete project proposal"
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            # Note: Template resolution happens in the node's execute method
            # before API calls, using the inputs parameter
            result = await node.execute({
                "prev_node": {"task_name": "project proposal"}
            })

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_template_in_task_body(self):
        """Test template resolution in task body field."""
        config = TodoCreateTaskConfig(
            task_list_id="AAMkAGI2TG95AAA=",
            title="Task",
            body="Details: {{input.prev_node.details}}"
        )
        node = create_node(config)

        mock_response = create_mock_response(201, {
            "id": "task-new",
            "title": "Task"
        })

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({
                "prev_node": {"details": "Important information"}
            })

        assert result["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
