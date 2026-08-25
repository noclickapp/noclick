"""
Mock tests for Google Tasks workflow node.

Tests all Google Tasks operations with mocked HTTP responses:
- Task Lists: list_task_lists, get_task_list, create_task_list, update_task_list, delete_task_list
- Tasks: list_tasks, get_task, create_task, update_task, delete_task

Uses httpx mocking to simulate Google Tasks API responses without real credentials.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from nodes.google_tasks_node import (
    GoogleTasksNode,
    GoogleTasksNodeConfig,
    GoogleTasksOAuthCredential,
    # Task List operations
    GoogleTasksListTaskListsConfig,
    GoogleTasksGetTaskListConfig,
    GoogleTasksCreateTaskListConfig,
    GoogleTasksUpdateTaskListConfig,
    GoogleTasksDeleteTaskListConfig,
    # Task operations
    GoogleTasksListTasksConfig,
    GoogleTasksGetTaskConfig,
    GoogleTasksCreateTaskConfig,
    GoogleTasksUpdateTaskConfig,
    GoogleTasksDeleteTaskConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================

TEST_CREDENTIALS = GoogleTasksOAuthCredential(
    access_token="mock_access_token",
    refresh_token="mock_refresh_token",
    expires_at="2099-12-31T23:59:59Z",
    email="test@example.com",
)


def create_node(config) -> GoogleTasksNode:
    """Create a GoogleTasksNode instance with the given config."""
    node_config = GoogleTasksNodeConfig(config=config, credentials=TEST_CREDENTIALS)
    return GoogleTasksNode(
        node_id="test-node",
        node_type="automation-google-tasks",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


def mock_response(status_code: int, json_data: dict = None, text: str = ""):
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text or ""
    response.json.return_value = json_data or {}
    return response


# ============================================================================
# Task List Operations Tests
# ============================================================================


class TestListTaskLists:
    """Test list_task_lists operation."""

    @pytest.mark.asyncio
    async def test_list_task_lists_success(self):
        """Test listing task lists returns lists successfully."""
        config = GoogleTasksListTaskListsConfig(max_results=10)
        node = create_node(config)

        mock_task_lists = {
            "items": [
                {
                    "id": "tasklist1",
                    "title": "My Tasks",
                    "updated": "2024-01-15T10:00:00Z",
                    "selfLink": "https://www.googleapis.com/tasks/v1/users/@me/lists/tasklist1",
                },
                {
                    "id": "tasklist2",
                    "title": "Work",
                    "updated": "2024-01-14T09:00:00Z",
                    "selfLink": "https://www.googleapis.com/tasks/v1/users/@me/lists/tasklist2",
                },
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_task_lists)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_all_task_lists"
            assert result["task_list_count"] == 2
            assert len(result["task_lists"]) == 2
            assert result["task_lists"][0]["id"] == "tasklist1"
            assert result["task_lists"][0]["title"] == "My Tasks"

    @pytest.mark.asyncio
    async def test_list_task_lists_empty(self):
        """Test listing task lists when none exist."""
        config = GoogleTasksListTaskListsConfig()
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"items": []})

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["task_list_count"] == 0
            assert result["task_lists"] == []


class TestGetTaskList:
    """Test get_task_list operation."""

    @pytest.mark.asyncio
    async def test_get_task_list_success(self):
        """Test getting a single task list."""
        config = GoogleTasksGetTaskListConfig(task_list_id="tasklist123")
        node = create_node(config)

        mock_task_list = {
            "id": "tasklist123",
            "title": "My Tasks",
            "updated": "2024-01-15T10:00:00Z",
            "selfLink": "https://www.googleapis.com/tasks/v1/users/@me/lists/tasklist123",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_task_list)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_task_list"
            assert result["task_list"]["id"] == "tasklist123"
            assert result["task_list"]["title"] == "My Tasks"


class TestCreateTaskList:
    """Test create_task_list operation."""

    @pytest.mark.asyncio
    async def test_create_task_list_success(self):
        """Test creating a new task list."""
        config = GoogleTasksCreateTaskListConfig(title="New Task List")
        node = create_node(config)

        mock_created = {
            "id": "new_tasklist_id",
            "title": "New Task List",
            "updated": "2024-01-15T10:00:00Z",
            "selfLink": "https://www.googleapis.com/tasks/v1/users/@me/lists/new_tasklist_id",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_new_task_list"
            assert result["task_list"]["id"] == "new_tasklist_id"
            assert result["task_list"]["title"] == "New Task List"


class TestUpdateTaskList:
    """Test update_task_list operation."""

    @pytest.mark.asyncio
    async def test_update_task_list_success(self):
        """Test updating an existing task list."""
        config = GoogleTasksUpdateTaskListConfig(
            task_list_id="tasklist123", title="Updated Title"
        )
        node = create_node(config)

        mock_updated = {
            "id": "tasklist123",
            "title": "Updated Title",
            "updated": "2024-01-15T11:00:00Z",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.put.return_value = mock_response(200, mock_updated)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_task_list_metadata"
            assert result["task_list"]["title"] == "Updated Title"


class TestDeleteTaskList:
    """Test delete_task_list operation."""

    @pytest.mark.asyncio
    async def test_delete_task_list_success(self):
        """Test deleting a task list."""
        config = GoogleTasksDeleteTaskListConfig(task_list_id="tasklist_to_delete")
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.delete.return_value = mock_response(204)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_task_list"
            assert result["task_list_id"] == "tasklist_to_delete"


# ============================================================================
# Task Operations Tests
# ============================================================================


class TestListTasks:
    """Test list_tasks operation."""

    @pytest.mark.asyncio
    async def test_list_tasks_success(self):
        """Test listing tasks in a task list."""
        config = GoogleTasksListTasksConfig(task_list_id="tasklist123", max_results=50)
        node = create_node(config)

        mock_tasks = {
            "items": [
                {
                    "id": "task1",
                    "title": "Buy groceries",
                    "status": "needsAction",
                    "due": "2024-01-20T00:00:00Z",
                    "notes": "Milk, eggs, bread",
                },
                {
                    "id": "task2",
                    "title": "Call dentist",
                    "status": "completed",
                    "completed": "2024-01-15T10:00:00Z",
                },
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_tasks)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_tasks_in_list"
            assert result["task_count"] == 2
            assert len(result["tasks"]) == 2
            assert result["tasks"][0]["title"] == "Buy groceries"


class TestGetTask:
    """Test get_task operation."""

    @pytest.mark.asyncio
    async def test_get_task_success(self):
        """Test getting a single task."""
        config = GoogleTasksGetTaskConfig(task_list_id="tasklist123", task_id="task456")
        node = create_node(config)

        mock_task = {
            "id": "task456",
            "title": "Important task",
            "status": "needsAction",
            "due": "2024-01-25T00:00:00Z",
            "notes": "Don't forget!",
            "links": [],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_task)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_task_from_list"
            assert result["task"]["id"] == "task456"
            assert result["task"]["title"] == "Important task"


class TestCreateTask:
    """Test create_task operation."""

    @pytest.mark.asyncio
    async def test_create_task_success(self):
        """Test creating a new task."""
        config = GoogleTasksCreateTaskConfig(
            task_list_id="tasklist123",
            title="New task",
            notes="Some notes",
            due="2024-02-01",
        )
        node = create_node(config)

        mock_created = {
            "id": "new_task_id",
            "title": "New task",
            "notes": "Some notes",
            "due": "2024-02-01T00:00:00Z",
            "status": "needsAction",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_new_task"
            assert result["task"]["id"] == "new_task_id"
            assert result["task"]["title"] == "New task"

    @pytest.mark.asyncio
    async def test_create_task_minimal(self):
        """Test creating a task with just a title."""
        config = GoogleTasksCreateTaskConfig(
            task_list_id="tasklist123", title="Simple task"
        )
        node = create_node(config)

        mock_created = {
            "id": "simple_task_id",
            "title": "Simple task",
            "status": "needsAction",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["task"]["title"] == "Simple task"


class TestUpdateTask:
    """Test update_task operation."""

    @pytest.mark.asyncio
    async def test_update_task_success(self):
        """Test updating an existing task."""
        config = GoogleTasksUpdateTaskConfig(
            task_list_id="tasklist123",
            task_id="task456",
            title="Updated title",
            status="completed",
        )
        node = create_node(config)

        # First call returns current task, second call returns updated task
        mock_current = {"id": "task456", "title": "Old title", "status": "needsAction"}
        mock_updated = {
            "id": "task456",
            "title": "Updated title",
            "status": "completed",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_current)
            mock_instance.put.return_value = mock_response(200, mock_updated)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_task_in_list"
            assert result["task"]["title"] == "Updated title"
            assert result["task"]["status"] == "completed"


class TestDeleteTask:
    """Test delete_task operation."""

    @pytest.mark.asyncio
    async def test_delete_task_success(self):
        """Test deleting a task."""
        config = GoogleTasksDeleteTaskConfig(
            task_list_id="tasklist123", task_id="task_to_delete"
        )
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.delete.return_value = mock_response(204)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_task_from_list"
            assert result["task_id"] == "task_to_delete"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_api_error_not_found(self):
        """Test handling of 404 errors."""
        config = GoogleTasksGetTaskListConfig(task_list_id="nonexistent")
        node = create_node(config)

        error_response = {"error": {"code": 404, "message": "Task list not found"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(
                404, error_response, "Task list not found"
            )

            with pytest.raises(Exception) as exc_info:
                await node.execute({})

            assert (
                "404" in str(exc_info.value)
                or "not found" in str(exc_info.value).lower()
            )

    @pytest.mark.asyncio
    async def test_api_error_unauthorized(self):
        """Test handling of 401 errors."""
        config = GoogleTasksListTaskListsConfig()
        node = create_node(config)

        error_response = {"error": {"code": 401, "message": "Invalid credentials"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(
                401, error_response, "Invalid credentials"
            )

            with pytest.raises(Exception) as exc_info:
                await node.execute({})

            assert (
                "401" in str(exc_info.value)
                or "credentials" in str(exc_info.value).lower()
            )


# ============================================================================
# Dynamic Field Options Tests
# ============================================================================


class TestDynamicFieldOptions:
    """Test dynamic field options loading."""

    @pytest.mark.asyncio
    async def test_load_task_list_options(self):
        """Test loading task list options for dropdown."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
            "email": "test@example.com",
        }

        mock_task_lists = {
            "items": [
                {"id": "list1", "title": "My Tasks"},
                {"id": "list2", "title": "Work Tasks"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_task_lists)

            result = await GoogleTasksNode.load_field_options(
                "task_list_id", credential_data, None
            )

            # Dynamic options return a list
            assert isinstance(result, list)
            assert len(result) == 2
            assert result[0]["value"] == "list1"
            assert result[0]["label"] == "My Tasks"
