"""
Mock tests for the ClickHouse Cloud management API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Organizations: list, get, update, list activities, get usage cost
- Services: list, create, get, update, delete, state, scaling, password
- Query Endpoints: get, upsert, delete
- Backups: list, get configuration
- ClickPipes: list, create, update state
- API Keys: list, create, delete
- Members & Invitations: list members, remove member, list/create/delete invitations
- Metrics: get Prometheus metrics
- Error handling: API errors, missing credentials
- Dynamic options: organization dropdown
"""

import base64

import pytest
from unittest.mock import Mock, patch

from nodes.clickhouse_node import (
    ClickHouseNode,
    ClickHouseNodeConfig,
    ClickHouseApiKeyCredential,
    ClickHouseListOrganizationsConfig,
    ClickHouseGetOrganizationConfig,
    ClickHouseUpdateOrganizationConfig,
    ClickHouseListActivitiesConfig,
    ClickHouseGetUsageCostConfig,
    ClickHouseListServicesConfig,
    ClickHouseCreateServiceConfig,
    ClickHouseGetServiceConfig,
    ClickHouseUpdateServiceConfig,
    ClickHouseDeleteServiceConfig,
    ClickHouseUpdateServiceStateConfig,
    ClickHouseUpdateServiceScalingConfig,
    ClickHouseUpdateServicePasswordConfig,
    ClickHouseGetQueryEndpointConfig,
    ClickHouseUpsertQueryEndpointConfig,
    ClickHouseDeleteQueryEndpointConfig,
    ClickHouseListBackupsConfig,
    ClickHouseGetBackupConfigurationConfig,
    ClickHouseListClickPipesConfig,
    ClickHouseCreateClickPipeConfig,
    ClickHouseUpdateClickPipeStateConfig,
    ClickHouseGetClickPipeConfig,
    ClickHouseDeleteClickPipeConfig,
    ClickHouseListKeysConfig,
    ClickHouseCreateKeyConfig,
    ClickHouseDeleteKeyConfig,
    ClickHouseListMembersConfig,
    ClickHouseRemoveMemberConfig,
    ClickHouseGetMemberConfig,
    ClickHouseUpdateMemberConfig,
    ClickHouseListInvitationsConfig,
    ClickHouseCreateInvitationConfig,
    ClickHouseDeleteInvitationConfig,
    ClickHouseGetInvitationConfig,
    ClickHouseGetBackupConfig,
    ClickHouseUpdateBackupConfigurationConfig,
    ClickHouseGetPrivateEndpointConfigConfig,
    ClickHouseUpdateServiceReplicaScalingConfig,
    ClickHouseGetPrometheusMetricsConfig,
    ClickHouseOnQueryResultsConfig,
)

ORG_ID = "org-123"
SERVICE_ID = "svc-456"


@pytest.fixture
def api_key_credentials():
    return ClickHouseApiKeyCredential(key_id="kid_test", key_secret="ksecret_test")


def create_clickhouse_node(config):
    return ClickHouseNode(
        node_id="test-clickhouse-node",
        node_type="automation-clickhouse",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, text=""):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, text="", capture=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager. Optionally captures request kwargs."""
    mock_response = create_mock_response(status_code, json_data, text)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        if capture is not None:
            capture.update(kwargs)
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


def _envelope(result):
    """ClickHouse management API wraps results in {result, status}."""
    return {"result": result, "status": 200}


# ============================================================================
# Organizations
# ============================================================================


class TestClickHouseOrganizationsMock:
    @pytest.mark.asyncio
    async def test_list_organizations(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseListOrganizationsConfig(), credentials=api_key_credentials
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope([{"id": ORG_ID, "name": "Acme"}]), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_organizations"
        assert len(result["data"]) == 1
        # Basic auth header is built from key_id:key_secret
        expected = base64.b64encode(b"kid_test:ksecret_test").decode()
        assert capture["headers"]["Authorization"] == f"Basic {expected}"

    @pytest.mark.asyncio
    async def test_get_organization(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetOrganizationConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope({"id": ORG_ID, "name": "Acme"}))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_organization"
        assert result["data"]["id"] == ORG_ID

    @pytest.mark.asyncio
    async def test_update_organization(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseUpdateOrganizationConfig(organization_id=ORG_ID, name="New Name"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"id": ORG_ID, "name": "New Name"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_organization"
        assert capture["json"]["name"] == "New Name"
        assert capture["method"] == "PATCH"

    @pytest.mark.asyncio
    async def test_list_activities(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseListActivitiesConfig(organization_id=ORG_ID, from_date="2026-06-01"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope([{"type": "service.create"}]), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_activities"
        assert capture["params"]["from_date"] == "2026-06-01"

    @pytest.mark.asyncio
    async def test_get_usage_cost(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetUsageCostConfig(
                organization_id=ORG_ID, from_date="2026-06-01", to_date="2026-06-30"
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope({"grandTotalCHC": 42}))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_usage_cost"


# ============================================================================
# Services
# ============================================================================


class TestClickHouseServicesMock:
    @pytest.mark.asyncio
    async def test_list_services(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseListServicesConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": SERVICE_ID, "name": "prod"}]))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_services"
        assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_create_service(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseCreateServiceConfig(
                organization_id=ORG_ID, name="analytics", provider="aws", region="us-east-1"
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"id": SERVICE_ID, "name": "analytics"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_service"
        assert capture["json"]["region"] == "us-east-1"
        assert capture["json"]["provider"] == "aws"

    @pytest.mark.asyncio
    async def test_get_service(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetServiceConfig(organization_id=ORG_ID, service_id=SERVICE_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope({"id": SERVICE_ID, "state": "running"}))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_service"
        assert result["data"]["id"] == SERVICE_ID

    @pytest.mark.asyncio
    async def test_update_service(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseUpdateServiceConfig(
                organization_id=ORG_ID, service_id=SERVICE_ID, name="renamed"
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"id": SERVICE_ID, "name": "renamed"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_service"
        assert capture["json"]["name"] == "renamed"

    @pytest.mark.asyncio
    async def test_delete_service(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseDeleteServiceConfig(organization_id=ORG_ID, service_id=SERVICE_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(204, capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_service"
        assert capture["method"] == "DELETE"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_update_service_state(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseUpdateServiceStateConfig(
                organization_id=ORG_ID, service_id=SERVICE_ID, command="stop"
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"state": "stopping"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_service_state"
        assert capture["json"]["command"] == "stop"

    @pytest.mark.asyncio
    async def test_update_service_scaling(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseUpdateServiceScalingConfig(
                organization_id=ORG_ID, service_id=SERVICE_ID,
                min_total_memory_gb="48", max_total_memory_gb="360",
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"id": SERVICE_ID}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_service_scaling"
        assert capture["json"]["minTotalMemoryGb"] == 48
        assert capture["json"]["maxTotalMemoryGb"] == 360

    @pytest.mark.asyncio
    async def test_update_service_password(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseUpdateServicePasswordConfig(
                organization_id=ORG_ID, service_id=SERVICE_ID, new_password_hash="abc123"
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"password": "set"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_service_password"
        assert capture["json"]["newPasswordHash"] == "abc123"

    @pytest.mark.asyncio
    async def test_get_private_endpoint_config(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetPrivateEndpointConfigConfig(organization_id=ORG_ID, service_id=SERVICE_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"endpointServiceId": "vpce-abc123"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_private_endpoint_config"
        assert "privateEndpointConfig" in capture["url"]

    @pytest.mark.asyncio
    async def test_update_service_replica_scaling(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseUpdateServiceReplicaScalingConfig(
                organization_id=ORG_ID, service_id=SERVICE_ID,
                min_replica_memory_gb="8", max_replica_memory_gb="32", num_replicas="3",
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"id": SERVICE_ID}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_service_replica_scaling"
        assert capture["json"]["minReplicaMemoryGb"] == 8
        assert capture["json"]["maxReplicaMemoryGb"] == 32
        assert capture["json"]["numReplicas"] == 3
        assert "replicaScaling" in capture["url"]


# ============================================================================
# Query Endpoints
# ============================================================================


class TestClickHouseQueryEndpointsMock:
    @pytest.mark.asyncio
    async def test_get_query_endpoint(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetQueryEndpointConfig(organization_id=ORG_ID, service_id=SERVICE_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope({"id": "qe-1"}))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_query_endpoint"

    @pytest.mark.asyncio
    async def test_upsert_query_endpoint(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseUpsertQueryEndpointConfig(
                organization_id=ORG_ID, service_id=SERVICE_ID,
                open_api_keys="sql_console_admin, sql_console_read_only",
                allowed_origins="https://app.example.com",
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"id": "qe-1"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upsert_query_endpoint"
        assert capture["json"]["openApiKeys"] == ["sql_console_admin", "sql_console_read_only"]
        assert capture["method"] == "POST"

    @pytest.mark.asyncio
    async def test_delete_query_endpoint(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseDeleteQueryEndpointConfig(organization_id=ORG_ID, service_id=SERVICE_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(204)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_query_endpoint"


# ============================================================================
# Backups
# ============================================================================


class TestClickHouseBackupsMock:
    @pytest.mark.asyncio
    async def test_list_backups(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseListBackupsConfig(organization_id=ORG_ID, service_id=SERVICE_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": "bk-1"}]))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_backups"

    @pytest.mark.asyncio
    async def test_get_backup_configuration(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetBackupConfigurationConfig(organization_id=ORG_ID, service_id=SERVICE_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope({"backupPeriodInHours": 24}))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_backup_configuration"

    @pytest.mark.asyncio
    async def test_get_backup(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetBackupConfig(organization_id=ORG_ID, service_id=SERVICE_ID, backup_id="bk-1"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope({"id": "bk-1", "status": "done"}))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_backup"
        assert result["data"]["id"] == "bk-1"

    @pytest.mark.asyncio
    async def test_update_backup_configuration(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseUpdateBackupConfigurationConfig(
                organization_id=ORG_ID, service_id=SERVICE_ID,
                backup_period_in_hours=24, backup_retention_period_in_hours=168,
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"backupPeriodInHours": 24}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_backup_configuration"
        assert capture["json"]["backupPeriodInHours"] == 24
        assert capture["json"]["backupRetentionPeriodInHours"] == 168
        assert capture["method"] == "PATCH"


# ============================================================================
# ClickPipes
# ============================================================================


class TestClickHouseClickPipesMock:
    @pytest.mark.asyncio
    async def test_list_clickpipes(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseListClickPipesConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope([{"id": "cp-1"}]), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_clickpipes"
        assert "/clickpipes" in capture["url"]
        assert "services" not in capture["url"]

    @pytest.mark.asyncio
    async def test_create_clickpipe(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseCreateClickPipeConfig(
                organization_id=ORG_ID,
                definition='{"name": "kafka-pipe", "source": {"kafka": {}}}',
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"id": "cp-1"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_clickpipe"
        assert capture["json"]["name"] == "kafka-pipe"
        assert "services" not in capture["url"]

    @pytest.mark.asyncio
    async def test_create_clickpipe_invalid_json(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseCreateClickPipeConfig(
                organization_id=ORG_ID, definition="not json{"
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        # No HTTP call should be made; invalid JSON short-circuits to an error.
        result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 400
        assert "Invalid ClickPipe definition JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_update_clickpipe_state(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseUpdateClickPipeStateConfig(
                organization_id=ORG_ID, clickpipe_id="cp-1", command="pause"
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"state": "paused"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_clickpipe_state"
        assert capture["json"]["command"] == "pause"
        assert "services" not in capture["url"]

    @pytest.mark.asyncio
    async def test_get_clickpipe(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetClickPipeConfig(organization_id=ORG_ID, clickpipe_id="cp-1"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"id": "cp-1", "state": "running"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_clickpipe"
        assert result["data"]["id"] == "cp-1"
        assert "services" not in capture["url"]

    @pytest.mark.asyncio
    async def test_delete_clickpipe(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseDeleteClickPipeConfig(organization_id=ORG_ID, clickpipe_id="cp-1"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(204, capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_clickpipe"
        assert capture["method"] == "DELETE"
        assert "services" not in capture["url"]


# ============================================================================
# API Keys
# ============================================================================


class TestClickHouseKeysMock:
    @pytest.mark.asyncio
    async def test_list_keys(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseListKeysConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": "key-1"}]))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_keys"

    @pytest.mark.asyncio
    async def test_create_key(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseCreateKeyConfig(organization_id=ORG_ID, name="ci-key", role="developer"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"key": {"id": "key-2"}, "keySecret": "s"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_key"
        assert capture["json"]["roles"] == ["developer"]

    @pytest.mark.asyncio
    async def test_delete_key(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseDeleteKeyConfig(organization_id=ORG_ID, key_id="key-2"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(204)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_key"


# ============================================================================
# Members & Invitations
# ============================================================================


class TestClickHouseMembersMock:
    @pytest.mark.asyncio
    async def test_list_members(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseListMembersConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope([{"userId": "u-1"}]))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_members"

    @pytest.mark.asyncio
    async def test_remove_member(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseRemoveMemberConfig(organization_id=ORG_ID, user_id="u-1"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(204)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "remove_member"

    @pytest.mark.asyncio
    async def test_get_member(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetMemberConfig(organization_id=ORG_ID, user_id="u-1"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope({"userId": "u-1", "role": "developer"}))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_member"
        assert result["data"]["userId"] == "u-1"

    @pytest.mark.asyncio
    async def test_update_member(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseUpdateMemberConfig(organization_id=ORG_ID, user_id="u-1", role="admin"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"userId": "u-1", "role": "admin"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_member"
        assert capture["json"]["role"] == "admin"
        assert capture["method"] == "PATCH"

    @pytest.mark.asyncio
    async def test_list_invitations(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseListInvitationsConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": "inv-1"}]))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_invitations"

    @pytest.mark.asyncio
    async def test_create_invitation(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseCreateInvitationConfig(
                organization_id=ORG_ID, email="new@example.com", role="developer"
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _envelope({"id": "inv-2"}), capture=capture)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_invitation"
        assert capture["json"]["email"] == "new@example.com"

    @pytest.mark.asyncio
    async def test_delete_invitation(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseDeleteInvitationConfig(organization_id=ORG_ID, invitation_id="inv-2"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(204)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_invitation"

    @pytest.mark.asyncio
    async def test_get_invitation(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetInvitationConfig(organization_id=ORG_ID, invitation_id="inv-1"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(200, _envelope({"id": "inv-1", "email": "user@example.com"}))
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_invitation"
        assert result["data"]["id"] == "inv-1"


# ============================================================================
# Metrics
# ============================================================================


class TestClickHouseMetricsMock:
    @pytest.mark.asyncio
    async def test_get_prometheus_metrics(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetPrometheusMetricsConfig(organization_id=ORG_ID, service_id=SERVICE_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        metrics_text = "# HELP ch_metric foo\nch_metric 1.0\n"
        mock_client = create_mock_client(200, json_data=None, text=metrics_text)
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_prometheus_metrics"
        assert result["data"]["metrics"] == metrics_text


# ============================================================================
# Error handling
# ============================================================================


class TestClickHouseErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = ClickHouseNodeConfig(
            config=ClickHouseGetServiceConfig(organization_id=ORG_ID, service_id="missing"),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        mock_client = create_mock_client(404, {"error": "Service not found"})
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = ClickHouseNodeConfig(
            config=ClickHouseListOrganizationsConfig(), credentials=None
        )
        node = create_clickhouse_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestClickHouseDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_organization_options(self):
        with patch(
            "nodes.clickhouse_node._clickhouse_request",
            return_value={
                "status": "success",
                "data": [{"id": ORG_ID, "name": "Acme Corp"}],
            },
        ):
            result = await ClickHouseNode.load_field_options(
                "organization_id",
                credential_data={"key_id": "kid_test", "key_secret": "ksecret_test"},
            )
        assert "options" in result
        assert result["options"][0]["value"] == ORG_ID
        assert result["options"][0]["label"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_load_options_unknown_field(self):
        result = await ClickHouseNode.load_field_options(
            "service_id", credential_data={"key_id": "k", "key_secret": "s"}
        )
        assert result == {"options": []}


# ============================================================================
# Trigger (poll-based: on_query_results)
# ============================================================================


async def _run_poll(node, activities, initial_state=None, status_code=200):
    """Run the poll trigger with an in-memory `_update_node_state` fake.

    The poll dedup is a CAS read-modify-write via `_update_node_state`; this fake
    applies the pure mutator once against `initial_state` and records the write,
    mirroring backend/nodes/tests/test_snowflake_node_mock.py::_run. Returns
    `(result, final_state)` so tests can assert both the emitted items and the
    persisted seen-set.
    """
    state = {"value": dict(initial_state or {})}

    async def _update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(state["value"]))
        if new_state is not None:
            state["value"] = dict(new_state)
        return result

    node._update_node_state = _update
    mock_client = create_mock_client(status_code, _envelope(activities))
    with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
        result = await node.execute({})
    return result, state["value"]


class TestClickHouseTriggerMock:
    @pytest.mark.asyncio
    async def test_resolve_trigger_payload_poll_returns_none(self):
        """Poll-based trigger returns None so execute() runs and polls the API."""
        result = ClickHouseNode.resolve_trigger_payload(
            {"webhook": "payload"}, {"operation": "on_query_results"}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_trigger_payload_normal_op_passthrough(self):
        """Non-trigger ops pass the payload through unchanged."""
        payload = {"some": "data"}
        result = ClickHouseNode.resolve_trigger_payload(
            payload, {"operation": "list_services"}
        )
        assert result is payload

    @pytest.mark.asyncio
    async def test_poll_baselines_on_first_run(self, api_key_credentials):
        """First poll (empty node state) BASELINES: it records every current
        activity id as seen and emits NOTHING, so enabling the trigger never
        floods the workflow with the entire existing audit log."""
        config = ClickHouseNodeConfig(
            config=ClickHouseOnQueryResultsConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)

        activities = [
            {"id": "act-1", "type": "service.create"},
            {"id": "act-2", "type": "service.stop"},
        ]
        result, final_state = await _run_poll(node, activities)

        assert result["status"] == "success"
        assert result["operation"] == "on_query_results"
        assert result["new_count"] == 0
        assert result["items"] == []
        assert result["total_in_window"] == 2
        assert node.trigger_produced_no_event(result) is True
        # Every current id is baselined so the NEXT poll only emits new ones.
        assert set(final_state["seen_activity_ids"]) == {"act-1", "act-2"}

    @pytest.mark.asyncio
    async def test_poll_second_poll_emits_only_new(self, api_key_credentials):
        """A second poll (seeded node state) emits only activities whose id is not
        already in the seen-set, and unions the new ids back into it."""
        config = ClickHouseNodeConfig(
            config=ClickHouseOnQueryResultsConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)

        activities = [
            {"id": "act-1", "type": "service.create"},
            {"id": "act-2", "type": "service.stop"},
            {"id": "act-3", "type": "service.start"},
            {"id": "act-4", "type": "service.stop"},
        ]
        result, final_state = await _run_poll(
            node, activities, initial_state={"seen_activity_ids": ["act-1", "act-2"]}
        )

        assert result["status"] == "success"
        assert result["new_count"] == 2
        assert [a["id"] for a in result["items"]] == ["act-3", "act-4"]
        assert node.trigger_produced_no_event(result) is False
        assert set(final_state["seen_activity_ids"]) == {"act-1", "act-2", "act-3", "act-4"}

    @pytest.mark.asyncio
    async def test_poll_dedupes_already_seen_activities(self, api_key_credentials):
        """A second poll with one previously-seen + one new activity emits only the new one."""
        config = ClickHouseNodeConfig(
            config=ClickHouseOnQueryResultsConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)

        # act-1 already seen from a prior poll; act-3 is new
        activities = [
            {"id": "act-1", "type": "service.create"},
            {"id": "act-3", "type": "service.start"},
        ]
        result, final_state = await _run_poll(
            node, activities, initial_state={"seen_activity_ids": ["act-1"]}
        )

        assert result["status"] == "success"
        assert result["new_count"] == 1
        assert [a["id"] for a in result["items"]] == ["act-3"]
        assert result["total_in_window"] == 2
        # Cursor now contains both ids
        assert set(final_state["seen_activity_ids"]) == {"act-1", "act-3"}

    @pytest.mark.asyncio
    async def test_poll_no_new_activities_skips_write(self, api_key_credentials):
        """When every current activity is already seen, nothing is emitted and the
        seen-set is left untouched (mutator returns None → no CAS write)."""
        config = ClickHouseNodeConfig(
            config=ClickHouseOnQueryResultsConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)

        activities = [
            {"id": "act-1", "type": "service.create"},
            {"id": "act-2", "type": "service.stop"},
        ]
        result, final_state = await _run_poll(
            node, activities, initial_state={"seen_activity_ids": ["act-1", "act-2"]}
        )

        assert result["new_count"] == 0
        assert result["items"] == []
        assert node.trigger_produced_no_event(result) is True
        assert set(final_state["seen_activity_ids"]) == {"act-1", "act-2"}

    @pytest.mark.asyncio
    async def test_poll_filters_by_activity_type(self, api_key_credentials):
        """activity_type filter restricts which activities are considered/emitted."""
        config = ClickHouseNodeConfig(
            config=ClickHouseOnQueryResultsConfig(
                organization_id=ORG_ID, activity_type="service.create"
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)

        activities = [
            {"id": "act-1", "type": "service.create"},
            {"id": "act-2", "type": "service.stop"},
        ]
        # Seeded state → not a first-run baseline, so the (filtered) new activity emits.
        result, _ = await _run_poll(
            node, activities, initial_state={"seen_activity_ids": ["act-0"]}
        )

        assert result["new_count"] == 1
        assert [a["id"] for a in result["items"]] == ["act-1"]

    @pytest.mark.asyncio
    async def test_poll_seeds_cursor_from_config_last_seen_id(self, api_key_credentials):
        """On the first run the config last_seen_id is folded into the baselined
        seen-set (optional cold-start seed); the first poll still baselines."""
        config = ClickHouseNodeConfig(
            config=ClickHouseOnQueryResultsConfig(
                organization_id=ORG_ID, last_seen_id="act-old"
            ),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)

        activities = [
            {"id": "act-1", "type": "service.create"},
            {"id": "act-2", "type": "service.stop"},
        ]
        result, final_state = await _run_poll(node, activities)

        # First poll baselines: nothing emitted, and the config seed is persisted
        # alongside the current ids.
        assert result["new_count"] == 0
        assert result["items"] == []
        assert set(final_state["seen_activity_ids"]) == {"act-old", "act-1", "act-2"}

    @pytest.mark.asyncio
    async def test_poll_api_error_propagates(self, api_key_credentials):
        """An API error during the poll is returned as an error result."""
        config = ClickHouseNodeConfig(
            config=ClickHouseOnQueryResultsConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)

        mock_client = create_mock_client(403, {"error": "Forbidden"})
        with patch("nodes.clickhouse_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 403

    @pytest.mark.asyncio
    async def test_trigger_produced_no_event_when_empty(self, api_key_credentials):
        """trigger_produced_no_event returns True when no new activities found."""
        config = ClickHouseNodeConfig(
            config=ClickHouseOnQueryResultsConfig(organization_id=ORG_ID),
            credentials=api_key_credentials,
        )
        node = create_clickhouse_node(config)
        # Output with 0 new items
        assert node.trigger_produced_no_event({"new_count": 0, "items": []}) is True
        # Output with items should not suppress
        assert node.trigger_produced_no_event({"new_count": 2, "items": [{"id": "a1"}, {"id": "a2"}]}) is False
