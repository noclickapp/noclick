"""
Mock tests for Apify node operations that require complex setup or can't be integration tested.

Tests operations like actor creation, builds, versions, and extended run operations using mocked responses.
Run: pytest backend/nodes/tests/test_apify_node_mock.py
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from nodes.apify_node import (
    ApifyNode,
    ApifyNodeConfig,
    ApifyApiTokenCredential,
    # Actor management
    ApifyCreateActorConfig,
    ApifyUpdateActorConfig,
    ApifyDeleteActorConfig,
    # Actor operations
    ApifyRunActorConfig,
    ApifyRunActorSyncConfig,
    ApifyRunActorSyncGetDatasetItemsConfig,
    # Actor builds
    ApifyBuildActorConfig,
    ApifyAbortBuildConfig,
    # Actor versions
    ApifyCreateActorVersionConfig,
    ApifyUpdateActorVersionConfig,
    ApifyDeleteActorVersionConfig,
    # Extended run operations
    ApifyMetamorphoseRunConfig,
    ApifyRebootRunConfig,
    ApifyAbortRunConfig,
    ApifyResurrectRunConfig,
    # Task management
    ApifyGetTaskConfig,
    ApifyRunTaskConfig,
    ApifyRunTaskSyncConfig,
    ApifyListTaskRunsConfig,
    ApifyGetTaskLastRunConfig,
    ApifyCreateTaskConfig,
    ApifyUpdateTaskConfig,
    ApifyDeleteTaskConfig,
    # Request queue operations
    ApifyGetRequestQueueConfig,
    # Request queue request operations
    ApifyAddQueueRequestConfig,
    ApifyUpdateQueueRequestConfig,
    ApifyDeleteQueueRequestConfig,
    # Environment variables operations
    ApifyListEnvVarsConfig,
    ApifyGetEnvVarConfig,
    ApifyCreateEnvVarConfig,
    ApifyUpdateEnvVarConfig,
    ApifyDeleteEnvVarConfig,
    # User/Account operations
    ApifyGetPublicUserConfig,
    ApifyGetUserLimitsConfig,
    ApifyUpdateUserLimitsConfig,
    ApifyGetMonthlyUsageConfig,
    # Additional resource operations
    ApifyGetDatasetStatisticsConfig,
    ApifyGetBuildLogConfig,
)


@pytest.fixture
def mock_credentials():
    """Fixture providing mock API credentials."""
    return ApifyApiTokenCredential(api_token="test_token_12345")


@pytest.fixture
def create_node():
    """Fixture to create a node with given config and credentials."""

    def _create_node(config, credentials):
        node_config = ApifyNodeConfig(config=config, credentials=credentials)
        return ApifyNode(
            node_id="test-node",
            node_type="automation-apify",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id=None,
            user_id=None,
            conversation_id=None,
        )

    return _create_node


class TestActorManagement:
    """Tests for actor CREATE/UPDATE/DELETE operations."""

    @pytest.mark.asyncio
    async def test_create_actor(self, create_node, mock_credentials):
        """Test creating a new actor."""
        config = ApifyCreateActorConfig(
            name="test-actor", title="Test Actor", description="A test actor"
        )
        node = create_node(config, mock_credentials)

        # Mock the HTTP request
        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "create_actor",
                    "data": {
                        "data": {
                            "id": "actor123",
                            "name": "test-actor",
                            "title": "Test Actor",
                        }
                    },
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            # Verify the request was made correctly
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"  # Method
            assert call_args[0][1] == "/acts"  # Endpoint

            # Verify response
            assert result["status"] == "success"
            assert result["action"] == "create_actor"
            assert result["data"]["data"]["name"] == "test-actor"

    @pytest.mark.asyncio
    async def test_update_actor(self, create_node, mock_credentials):
        """Test updating an actor."""
        config = ApifyUpdateActorConfig(
            actor_id="actor123", title="Updated Title", is_public=True
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "update_actor",
                    "data": {"data": {"id": "actor123", "title": "Updated Title"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "PUT"
            assert "/acts/actor123" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_actor(self, create_node, mock_credentials):
        """Test deleting an actor."""
        config = ApifyDeleteActorConfig(actor_id="actor123")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(return_value={"status": "success", "action": "delete_actor"}),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "DELETE"
            assert "/acts/actor123" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_run_actor(self, create_node, mock_credentials):
        """Test running an actor."""
        import json

        config = ApifyRunActorConfig(
            actor_id="actor123",
            input_body=json.dumps({"testInput": "value"}),
            timeout_secs=60,
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "run_actor_asynchronously",
                    "data": {"data": {"id": "run456", "status": "RUNNING"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/acts/actor123/runs" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_run_actor_sync(self, create_node, mock_credentials):
        """Test running an actor synchronously."""
        import json

        config = ApifyRunActorSyncConfig(
            actor_id="actor123",
            input_body=json.dumps({"testInput": "value"}),
            timeout_secs=120,
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "run_actor_synchronously",
                    "data": {"data": {"id": "run456", "status": "SUCCEEDED"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/acts/actor123/run-sync" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_run_actor_sync_get_dataset_items(
        self, create_node, mock_credentials
    ):
        """Test running actor sync and getting dataset items."""
        import json

        config = ApifyRunActorSyncGetDatasetItemsConfig(
            actor_id="actor123",
            input_body=json.dumps({"testInput": "value"}),
            timeout_secs=120,
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "run_actor_sync_and_get_dataset_items",
                    "data": [{"item1": "data1"}, {"item2": "data2"}],
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/acts/actor123/run-sync-get-dataset-items" in call_args[0][1]
            assert result["status"] == "success"


class TestActorBuilds:
    """Tests for actor build operations."""

    @pytest.mark.asyncio
    async def test_build_actor(self, create_node, mock_credentials):
        """Test starting an actor build."""
        config = ApifyBuildActorConfig(
            actor_id="actor123",
            version_number="0.1",
            use_cache=True,
            wait_for_finish=10,
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "start_actor_build",
                    "data": {"data": {"id": "build456", "status": "RUNNING"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/acts/actor123/builds" in call_args[0][1]
            assert result["status"] == "success"
            assert result["data"]["data"]["status"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_abort_build(self, create_node, mock_credentials):
        """Test aborting an actor build."""
        config = ApifyAbortBuildConfig(actor_id="actor123", build_id="build456")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "abort_actor_build",
                    "data": {"data": {"status": "ABORTING"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/acts/actor123/builds/build456/abort" in call_args[0][1]
            assert result["status"] == "success"


class TestActorVersions:
    """Tests for actor version management."""

    @pytest.mark.asyncio
    async def test_create_actor_version(self, create_node, mock_credentials):
        """Test creating a new actor version."""
        config = ApifyCreateActorVersionConfig(
            actor_id="actor123",
            version_number="1.0",
            build_tag="latest",
            source_type="SOURCE_FILES",
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "create_actor_version",
                    "data": {"data": {"versionNumber": "1.0"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/acts/actor123/versions" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_actor_version(self, create_node, mock_credentials):
        """Test updating an actor version."""
        config = ApifyUpdateActorVersionConfig(
            actor_id="actor123", version_number="1.0", build_tag="stable"
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={"status": "success", "action": "update_actor_version"}
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "PUT"
            assert "/acts/actor123/versions/1.0" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_delete_actor_version(self, create_node, mock_credentials):
        """Test deleting an actor version."""
        config = ApifyDeleteActorVersionConfig(
            actor_id="actor123", version_number="0.9"
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={"status": "success", "action": "delete_actor_version"}
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "DELETE"
            assert "/acts/actor123/versions/0.9" in call_args[0][1]


class TestExtendedRunOperations:
    """Tests for extended actor run operations."""

    @pytest.mark.asyncio
    async def test_metamorphose_run(self, create_node, mock_credentials):
        """Test metamorphosing an actor run."""
        config = ApifyMetamorphoseRunConfig(
            run_id="run123",
            target_actor_id="actor456",
            target_actor_build="latest",
            input_body='{"url": "https://example.com"}',
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "metamorphose_actor_run",
                    "data": {"data": {"status": "RUNNING"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/actor-runs/run123/metamorphose" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_reboot_run(self, create_node, mock_credentials):
        """Test rebooting an actor run."""
        config = ApifyRebootRunConfig(run_id="run123")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "reboot_actor_run",
                    "data": {"data": {"status": "RUNNING"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/actor-runs/run123/reboot" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_abort_run(self, create_node, mock_credentials):
        """Test aborting an actor run."""
        config = ApifyAbortRunConfig(run_id="run123", gracefully=True)
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "abort_actor_run",
                    "data": {"data": {"status": "ABORTING"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/actor-runs/run123/abort" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_resurrect_run(self, create_node, mock_credentials):
        """Test resurrecting an actor run."""
        config = ApifyResurrectRunConfig(run_id="run123")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "resurrect_actor_run",
                    "data": {"data": {"status": "RUNNING"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/actor-runs/run123/resurrect" in call_args[0][1]
            assert result["status"] == "success"


class TestTaskManagement:
    """Tests for actor task management."""

    @pytest.mark.asyncio
    async def test_create_task(self, create_node, mock_credentials):
        """Test creating an actor task."""
        config = ApifyCreateTaskConfig(
            actor_id="actor123",
            name="test-task",
            title="Test Task",
            input_body='{"url": "https://example.com"}',
            memory_mbytes=256,
            timeout_secs=300,
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "create_actor_task",
                    "data": {"data": {"id": "task789", "name": "test-task"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/actor-tasks" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_task(self, create_node, mock_credentials):
        """Test updating an actor task."""
        config = ApifyUpdateTaskConfig(
            task_id="task789", title="Updated Task", memory_mbytes=512
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={"status": "success", "action": "update_actor_task"}
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "PUT"
            assert "/actor-tasks/task789" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_delete_task(self, create_node, mock_credentials):
        """Test deleting an actor task."""
        config = ApifyDeleteTaskConfig(task_id="task789")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={"status": "success", "action": "delete_actor_task"}
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "DELETE"
            assert "/actor-tasks/task789" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_task(self, create_node, mock_credentials):
        """Test getting a task."""
        config = ApifyGetTaskConfig(task_id="task789")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "get_actor_task",
                    "data": {"data": {"id": "task789", "name": "test-task"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/actor-tasks/task789" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_run_task(self, create_node, mock_credentials):
        """Test running a task."""
        config = ApifyRunTaskConfig(task_id="task789", timeout_secs=60)
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "run_actor_task_asynchronously",
                    "data": {"data": {"id": "run123", "status": "RUNNING"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/actor-tasks/task789/runs" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_run_task_sync(self, create_node, mock_credentials):
        """Test running a task synchronously."""
        config = ApifyRunTaskSyncConfig(task_id="task789", timeout_secs=120)
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "run_actor_task_synchronously",
                    "data": {"data": {"id": "run123", "status": "SUCCEEDED"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/actor-tasks/task789/run-sync" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_task_runs(self, create_node, mock_credentials):
        """Test listing task runs."""
        config = ApifyListTaskRunsConfig(task_id="task789")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "list_task_runs",
                    "data": {"data": {"items": []}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/actor-tasks/task789/runs" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_task_last_run(self, create_node, mock_credentials):
        """Test getting last task run."""
        config = ApifyGetTaskLastRunConfig(task_id="task789")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "get_task_last_run",
                    "data": {"data": {"id": "run123", "status": "SUCCEEDED"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/actor-tasks/task789/runs/last" in call_args[0][1]
            assert result["status"] == "success"


class TestRequestQueueRequests:
    """Tests for request queue request management operations."""

    @pytest.mark.asyncio
    async def test_add_queue_request(self, create_node, mock_credentials):
        """Test adding a request to a queue."""
        config = ApifyAddQueueRequestConfig(
            queue_id="queue123",
            url="https://example.com/page1",
            method="GET",
            unique_key="page1",
            user_data='{"priority": 1}',
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "add_request_to_queue",
                    "data": {
                        "data": {"id": "req456", "url": "https://example.com/page1"}
                    },
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/request-queues/queue123/requests" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_queue_request(self, create_node, mock_credentials):
        """Test updating a request in a queue."""
        config = ApifyUpdateQueueRequestConfig(
            queue_id="queue123", request_id="req456", user_data='{"priority": 2}'
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={"status": "success", "action": "update_request_in_queue"}
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "PUT"
            assert "/request-queues/queue123/requests/req456" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_delete_queue_request(self, create_node, mock_credentials):
        """Test deleting a request from a queue."""
        config = ApifyDeleteQueueRequestConfig(queue_id="queue123", request_id="req456")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "delete_request_from_queue",
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "DELETE"
            assert "/request-queues/queue123/requests/req456" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_request_queue(self, create_node, mock_credentials):
        """Test getting a request queue."""
        config = ApifyGetRequestQueueConfig(queue_id="queue123")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "get_request_queue",
                    "data": {
                        "data": {
                            "id": "queue123",
                            "name": "test-queue",
                            "totalRequestCount": 10,
                        }
                    },
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/request-queues/queue123" in call_args[0][1]
            assert result["status"] == "success"


class TestEnvironmentVariables:
    """Tests for environment variables operations."""

    @pytest.mark.asyncio
    async def test_list_env_vars(self, create_node, mock_credentials):
        """Test listing environment variables."""
        config = ApifyListEnvVarsConfig(actor_id="actor123", version_number="1.0")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "list_environment_variables",
                    "data": {"data": {"items": [{"name": "API_KEY", "value": "***"}]}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/acts/actor123/versions/1.0/env-vars" in call_args[0][1]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_env_var(self, create_node, mock_credentials):
        """Test getting a specific environment variable."""
        config = ApifyGetEnvVarConfig(
            actor_id="actor123", version_number="1.0", env_var_name="API_KEY"
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "get_environment_variable",
                    "data": {"data": {"name": "API_KEY", "value": "***"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/acts/actor123/versions/1.0/env-vars/API_KEY" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_create_env_var(self, create_node, mock_credentials):
        """Test creating an environment variable."""
        config = ApifyCreateEnvVarConfig(
            actor_id="actor123",
            version_number="1.0",
            name="NEW_VAR",
            value="test_value",
            is_secret=True,
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "create_environment_variable",
                    "data": {"data": {"name": "NEW_VAR"}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/acts/actor123/versions/1.0/env-vars" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_update_env_var(self, create_node, mock_credentials):
        """Test updating an environment variable."""
        config = ApifyUpdateEnvVarConfig(
            actor_id="actor123",
            version_number="1.0",
            env_var_name="API_KEY",
            value="new_value",
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "update_environment_variable",
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "PUT"
            assert "/acts/actor123/versions/1.0/env-vars/API_KEY" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_delete_env_var(self, create_node, mock_credentials):
        """Test deleting an environment variable."""
        config = ApifyDeleteEnvVarConfig(
            actor_id="actor123", version_number="1.0", env_var_name="OLD_VAR"
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "delete_environment_variable",
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "DELETE"
            assert "/acts/actor123/versions/1.0/env-vars/OLD_VAR" in call_args[0][1]


class TestUserAccountOperations:
    """Tests for user and account management operations."""

    @pytest.mark.asyncio
    async def test_get_public_user(self, create_node, mock_credentials):
        """Test getting public user information."""
        config = ApifyGetPublicUserConfig(user_id="user123")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "get_public_user_info",
                    "data": {"data": {"username": "testuser", "profile": {}}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/users/user123" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_user_limits(self, create_node, mock_credentials):
        """Test getting user limits."""
        config = ApifyGetUserLimitsConfig()
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "get_account_limits_and_usage",
                    "data": {"data": {"maxMonthlyUsageUsd": 100}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/users/me/limits" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_update_user_limits(self, create_node, mock_credentials):
        """Test updating user limits."""
        config = ApifyUpdateUserLimitsConfig(
            user_id="user123", max_monthly_usage_usd=200.0, max_actors_per_user=50
        )
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={"status": "success", "action": "update_account_limits"}
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "PUT"
            assert "/users/user123/limits" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_monthly_usage(self, create_node, mock_credentials):
        """Test getting monthly usage statistics."""
        config = ApifyGetMonthlyUsageConfig()
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "get_monthly_usage_stats",
                    "data": {"data": {"computeUnitUsage": 1000}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/users/me/usage/monthly" in call_args[0][1]


class TestAdditionalResources:
    """Tests for additional resource operations."""

    @pytest.mark.asyncio
    async def test_get_dataset_statistics(self, create_node, mock_credentials):
        """Test getting dataset statistics."""
        config = ApifyGetDatasetStatisticsConfig(dataset_id="dataset123")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "get_dataset_statistics",
                    "data": {"data": {"itemCount": 1000, "sizeBytes": 50000}},
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/datasets/dataset123/stats" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_build_log(self, create_node, mock_credentials):
        """Test getting build log."""
        config = ApifyGetBuildLogConfig(actor_id="actor123", build_id="build456")
        node = create_node(config, mock_credentials)

        with patch.object(
            node,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "action": "get_actor_build_log",
                    "data": "Build started...\nBuild completed successfully",
                }
            ),
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/acts/actor123/builds/build456/log" in call_args[0][1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
