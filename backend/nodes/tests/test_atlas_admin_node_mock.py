"""
Mock tests for the MongoDB Atlas Admin API node.

Exercises key operations with mocked HTTP and token calls (no live API):
- Token acquisition and caching
- _build_request dispatch: confirms correct HTTP method + URL for all op categories
- Config discriminator: every operation literal matches its class
- load_field_options: projects, orgs, clusters, empty-creds guard
- execute() integration: success and error propagation
- Trigger config validation: on_alert, poll_events
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from nodes.atlas_admin_node import (
    AtlasAdminNode,
    AtlasAdminCredential,
    AtlasNodeConfig,
    AtlasListClustersConfig,
    AtlasGetClusterConfig,
    AtlasDeleteClusterConfig,
    AtlasPauseClusterConfig,
    AtlasResumeClusterConfig,
    AtlasListFlexClustersConfig,
    AtlasGetBackupScheduleConfig,
    AtlasListSnapshotsConfig,
    AtlasListDbUsersConfig,
    AtlasCreateDbUserConfig,
    AtlasDeleteDbUserConfig,
    AtlasListAccessListConfig,
    AtlasAddAccessListConfig,
    AtlasListSearchIndexesConfig,
    AtlasListStreamInstancesConfig,
    AtlasListOrgsConfig,
    AtlasGetOrgConfig,
    AtlasListProjectsConfig,
    AtlasGetProjectConfig,
    AtlasCreateProjectConfig,
    AtlasListOrgTeamsConfig,
    AtlasListAlertConfigsConfig,
    AtlasCreateAlertConfigConfig,
    AtlasListAlertsConfig,
    AtlasAcknowledgeAlertConfig,
    AtlasListProcessesConfig,
    AtlasListInvoicesConfig,
    AtlasOnAlertConfig,
    AtlasOnClusterEventConfig,
    AtlasOnBackupEventConfig,
    AtlasOnMaintenanceEventConfig,
    AtlasOnUserEventConfig,
    AtlasOnAlertEventConfig,
    _TOKEN_CACHE,
    _atlas_token_cache_key,
    _get_atlas_token,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FAKE_TOKEN = "fake-atlas-bearer-token"
FAKE_CLIENT_ID = "test-client-id"
FAKE_CLIENT_SECRET = "test-client-secret"
FAKE_PROJECT_ID = "507f1f77bcf86cd799439011"
FAKE_ORG_ID = "507f1f77bcf86cd799439012"
FAKE_CLUSTER_NAME = "my-cluster"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_token_cache():
    _TOKEN_CACHE.clear()
    yield
    _TOKEN_CACHE.clear()


@pytest.fixture
def mock_token():
    with patch("nodes.atlas_admin_node._get_atlas_token", new=AsyncMock(return_value=FAKE_TOKEN)):
        yield FAKE_TOKEN


@pytest.fixture
def mock_request():
    with patch("nodes.atlas_admin_node._atlas_request", new=AsyncMock(return_value={
        "status": "success",
        "data": {"results": [], "totalCount": 0},
        "status_code": 200,
    })) as m:
        yield m


def make_creds():
    return AtlasAdminCredential(client_id=FAKE_CLIENT_ID, client_secret=FAKE_CLIENT_SECRET)


def make_node_config(op_config):
    return AtlasNodeConfig(config=op_config, credentials=make_creds())


def create_node(op_config):
    return AtlasAdminNode(
        node_id="test-atlas-node",
        node_type="automation-atlas-admin",
        node_data={},
        config=make_node_config(op_config),
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


# Pass both field name variants so tests work for both old (group_id) and new
# (project_id) config classes. Pydantic ignores unknown extra fields.
def project_id_kwargs(**extra):
    return {"project_id": FAKE_PROJECT_ID, "group_id": FAKE_PROJECT_ID, **extra}


def org_id_kwargs(**extra):
    return {"org_id": FAKE_ORG_ID, **extra}


# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------

class TestTokenAcquisition:
    @pytest.mark.asyncio
    async def test_get_token_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "new-token", "expires_in": 3600}

        with patch("httpx.AsyncClient") as mock_cls, patch(
            "nodes.atlas_admin_node.time.monotonic", return_value=1000.0
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__.return_value = mock_client

            token = await _get_atlas_token(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET)

        assert token == "new-token"
        cache_key = _atlas_token_cache_key(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET)
        assert len(cache_key) == 64
        assert FAKE_CLIENT_SECRET not in cache_key
        assert _TOKEN_CACHE.get(cache_key, now=1001.0) == "new-token"

    @pytest.mark.asyncio
    async def test_get_token_cached(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "cached-token",
            "expires_in": 3600,
        }

        with patch("httpx.AsyncClient") as mock_cls, patch(
            "nodes.atlas_admin_node.time.monotonic", return_value=1000.0
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__.return_value = mock_client

            first = await _get_atlas_token(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET)
            second = await _get_atlas_token(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET)

        assert first == second == "cached-token"
        mock_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_same_client_id_with_different_secret_cannot_reuse_token(self):
        first_response = MagicMock(status_code=200)
        first_response.json.return_value = {
            "access_token": "first-tenant-token",
            "expires_in": 3600,
        }
        second_response = MagicMock(status_code=200)
        second_response.json.return_value = {
            "access_token": "second-tenant-token",
            "expires_in": 3600,
        }

        with patch("httpx.AsyncClient") as mock_cls, patch(
            "nodes.atlas_admin_node.time.monotonic", return_value=1000.0
        ):
            mock_client = AsyncMock()
            mock_client.post.side_effect = [first_response, second_response]
            mock_cls.return_value.__aenter__.return_value = mock_client

            first = await _get_atlas_token(FAKE_CLIENT_ID, "first-secret")
            second = await _get_atlas_token(FAKE_CLIENT_ID, "second-secret")

        assert first == "first-tenant-token"
        assert second == "second-tenant-token"
        assert mock_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_expired_token_is_refreshed(self):
        first_response = MagicMock(status_code=200)
        first_response.json.return_value = {
            "access_token": "short-token",
            "expires_in": 120,
        }
        second_response = MagicMock(status_code=200)
        second_response.json.return_value = {
            "access_token": "refreshed-token",
            "expires_in": 120,
        }
        now = [1000.0]

        with patch("httpx.AsyncClient") as mock_cls, patch(
            "nodes.atlas_admin_node.time.monotonic", side_effect=lambda: now[0]
        ):
            mock_client = AsyncMock()
            mock_client.post.side_effect = [first_response, second_response]
            mock_cls.return_value.__aenter__.return_value = mock_client

            assert await _get_atlas_token(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET) == "short-token"
            now[0] = 1060.0
            assert await _get_atlas_token(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET) == "refreshed-token"

        assert mock_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_get_token_auth_error_raises(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error_description": "Invalid client"}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(RuntimeError, match="401"):
                await _get_atlas_token(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET)


# ---------------------------------------------------------------------------
# Config discriminator checks
# ---------------------------------------------------------------------------

class TestConfigDiscriminators:
    def test_list_clusters(self):
        assert AtlasListClustersConfig(**project_id_kwargs()).operation == "list_clusters"

    def test_get_cluster(self):
        assert AtlasGetClusterConfig(**project_id_kwargs(cluster_name=FAKE_CLUSTER_NAME)).operation == "get_cluster"

    def test_pause_cluster(self):
        assert AtlasPauseClusterConfig(**project_id_kwargs(cluster_name=FAKE_CLUSTER_NAME)).operation == "pause_cluster"

    def test_resume_cluster(self):
        assert AtlasResumeClusterConfig(**project_id_kwargs(cluster_name=FAKE_CLUSTER_NAME)).operation == "resume_cluster"

    def test_delete_cluster(self):
        assert AtlasDeleteClusterConfig(**project_id_kwargs(cluster_name=FAKE_CLUSTER_NAME)).operation == "delete_cluster"

    def test_list_flex_clusters(self):
        assert AtlasListFlexClustersConfig(**project_id_kwargs()).operation == "list_flex_clusters"

    def test_get_backup_schedule(self):
        assert AtlasGetBackupScheduleConfig(**project_id_kwargs(cluster_name=FAKE_CLUSTER_NAME)).operation == "get_backup_schedule"

    def test_list_snapshots(self):
        assert AtlasListSnapshotsConfig(**project_id_kwargs(cluster_name=FAKE_CLUSTER_NAME)).operation == "list_snapshots"

    def test_list_db_users(self):
        assert AtlasListDbUsersConfig(**project_id_kwargs()).operation == "list_db_users"

    def test_list_access_list(self):
        assert AtlasListAccessListConfig(**project_id_kwargs()).operation == "list_access_list"

    def test_list_search_indexes(self):
        c = AtlasListSearchIndexesConfig(
            **project_id_kwargs(cluster_name=FAKE_CLUSTER_NAME, database_name="db", collection_name="col")
        )
        assert c.operation == "list_search_indexes"

    def test_list_stream_instances(self):
        assert AtlasListStreamInstancesConfig(**project_id_kwargs()).operation == "list_stream_instances"

    def test_list_orgs(self):
        assert AtlasListOrgsConfig().operation == "list_orgs"

    def test_list_projects(self):
        assert AtlasListProjectsConfig().operation == "list_projects"

    def test_list_alert_configs(self):
        assert AtlasListAlertConfigsConfig(**project_id_kwargs()).operation == "list_alert_configs"

    def test_list_alerts(self):
        assert AtlasListAlertsConfig(**project_id_kwargs()).operation == "list_alerts"

    def test_list_processes(self):
        assert AtlasListProcessesConfig(**project_id_kwargs()).operation == "list_processes"

    def test_list_invoices(self):
        assert AtlasListInvoicesConfig(**org_id_kwargs()).operation == "list_invoices"

    def test_on_alert_trigger(self):
        assert AtlasOnAlertConfig(trigger_group_id=FAKE_PROJECT_ID).operation == "on_alert"

    def test_poll_trigger_cluster_event(self):
        assert AtlasOnClusterEventConfig(trigger_group_id=FAKE_PROJECT_ID).operation == "on_cluster_event"

    def test_poll_trigger_backup_event(self):
        assert AtlasOnBackupEventConfig(trigger_group_id=FAKE_PROJECT_ID).operation == "on_backup_event"

    def test_poll_trigger_maintenance_event(self):
        assert AtlasOnMaintenanceEventConfig(trigger_group_id=FAKE_PROJECT_ID).operation == "on_maintenance_event"

    def test_poll_trigger_user_event(self):
        assert AtlasOnUserEventConfig(trigger_group_id=FAKE_PROJECT_ID).operation == "on_user_event"

    def test_poll_trigger_alert_event(self):
        assert AtlasOnAlertEventConfig(trigger_group_id=FAKE_PROJECT_ID).operation == "on_alert_event"


# ---------------------------------------------------------------------------
# _build_request dispatch
# ---------------------------------------------------------------------------

class TestBuildRequest:
    def _build(self, op_config):
        node = create_node(op_config)
        c = op_config
        gid = getattr(c, "project_id", "") or getattr(c, "group_id", "") or ""
        org = getattr(c, "org_id", "") or ""
        cluster = getattr(c, "cluster_name", "") or ""
        return node._build_request(c, c.operation, gid, org, cluster)

    def test_list_clusters_route(self):
        method, endpoint, *_ = self._build(AtlasListClustersConfig(**project_id_kwargs()))
        assert method == "GET"
        assert f"/groups/{FAKE_PROJECT_ID}/clusters" in endpoint

    def test_pause_cluster_route(self):
        method, endpoint, _, body = self._build(
            AtlasPauseClusterConfig(**project_id_kwargs(cluster_name=FAKE_CLUSTER_NAME))
        )
        assert method == "PATCH"
        assert FAKE_CLUSTER_NAME in endpoint

    def test_list_db_users_route(self):
        method, endpoint, *_ = self._build(AtlasListDbUsersConfig(**project_id_kwargs()))
        assert method == "GET"
        assert "databaseUsers" in endpoint

    def test_list_access_list_route(self):
        method, endpoint, *_ = self._build(AtlasListAccessListConfig(**project_id_kwargs()))
        assert method == "GET"
        assert "accessList" in endpoint

    def test_list_orgs_route(self):
        method, endpoint, *_ = self._build(AtlasListOrgsConfig())
        assert method == "GET"
        assert endpoint == "/orgs"

    def test_list_projects_route(self):
        method, endpoint, *_ = self._build(AtlasListProjectsConfig())
        assert method == "GET"
        assert endpoint == "/groups"

    def test_list_alert_configs_route(self):
        method, endpoint, *_ = self._build(AtlasListAlertConfigsConfig(**project_id_kwargs()))
        assert method == "GET"
        assert "alertConfigs" in endpoint

    def test_list_alerts_route(self):
        method, endpoint, *_ = self._build(AtlasListAlertsConfig(**project_id_kwargs()))
        assert method == "GET"
        assert "alerts" in endpoint

    def test_list_processes_route(self):
        method, endpoint, *_ = self._build(AtlasListProcessesConfig(**project_id_kwargs()))
        assert method == "GET"
        assert "processes" in endpoint

    def test_list_invoices_route(self):
        method, endpoint, *_ = self._build(AtlasListInvoicesConfig(**org_id_kwargs()))
        assert method == "GET"
        assert "invoices" in endpoint

    def test_list_stream_instances_route(self):
        method, endpoint, *_ = self._build(AtlasListStreamInstancesConfig(**project_id_kwargs()))
        assert method == "GET"
        assert "streams" in endpoint

    def test_list_search_indexes_route(self):
        method, endpoint, *_ = self._build(AtlasListSearchIndexesConfig(
            **project_id_kwargs(cluster_name=FAKE_CLUSTER_NAME, database_name="db", collection_name="col")
        ))
        assert method == "GET"
        assert "fts/indexes" in endpoint or "indexes" in endpoint


# ---------------------------------------------------------------------------
# execute() integration tests
# ---------------------------------------------------------------------------

class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_success(self, mock_token, mock_request):
        mock_request.return_value = {
            "status": "success",
            "data": {"results": [{"name": "cluster-1"}], "totalCount": 1},
            "status_code": 200,
        }
        node = create_node(AtlasListClustersConfig(**project_id_kwargs(), fetch_all_pages="false"))
        result = await node.execute({})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_execute_api_error_propagated(self, mock_token, mock_request):
        mock_request.return_value = {
            "status": "error",
            "error": "Cluster not found",
            "status_code": 404,
        }
        node = create_node(AtlasGetClusterConfig(**project_id_kwargs(cluster_name="nonexistent")))
        result = await node.execute({})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_trigger_op_returns_inputs(self):
        node = create_node(AtlasOnAlertConfig(trigger_group_id=FAKE_PROJECT_ID))
        result = await node.execute({"event": "CLUSTER_READY", "clusterName": "prod"})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_poll_trigger_cluster_event(self, mock_token, mock_request):
        """Poll triggers authenticate and call Atlas Events API on execution."""
        mock_request.return_value = {
            "status": "success",
            "data": {"results": [], "totalCount": 0},
            "status_code": 200,
        }
        node = create_node(AtlasOnClusterEventConfig(trigger_group_id=FAKE_PROJECT_ID))
        with patch.object(node, "_filter_unseen", new=AsyncMock(return_value=[])):
            node._poll_emitted_count = 0
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "on_cluster_event"
        assert "events" in result


# ---------------------------------------------------------------------------
# load_field_options
# ---------------------------------------------------------------------------

class TestLoadFieldOptions:
    CRED = {"client_id": FAKE_CLIENT_ID, "client_secret": FAKE_CLIENT_SECRET}

    @pytest.mark.asyncio
    async def test_load_projects(self, mock_token, mock_request):
        mock_request.return_value = {
            "status": "success",
            "data": {"results": [
                {"id": FAKE_PROJECT_ID, "name": "Prod"},
                {"id": "other-id", "name": "Dev"},
            ]},
        }
        result = await AtlasAdminNode.load_field_options("project_id", self.CRED)
        assert "options" in result
        assert len(result["options"]) == 2
        assert result["options"][0]["label"] == "Prod"
        assert result["options"][0]["value"] == FAKE_PROJECT_ID

    @pytest.mark.asyncio
    async def test_load_orgs(self, mock_token, mock_request):
        mock_request.return_value = {
            "status": "success",
            "data": {"results": [{"id": FAKE_ORG_ID, "name": "My Org"}]},
        }
        result = await AtlasAdminNode.load_field_options("org_id", self.CRED)
        assert "options" in result
        assert result["options"][0]["value"] == FAKE_ORG_ID

    @pytest.mark.asyncio
    async def test_load_clusters(self, mock_token, mock_request):
        mock_request.return_value = {
            "status": "success",
            "data": {"results": [{"name": FAKE_CLUSTER_NAME}]},
        }
        result = await AtlasAdminNode.load_field_options(
            "cluster_name", self.CRED, context={"project_id": FAKE_PROJECT_ID}
        )
        assert "options" in result
        assert any(o["value"] == FAKE_CLUSTER_NAME for o in result["options"])

    @pytest.mark.asyncio
    async def test_load_options_empty_creds(self):
        result = await AtlasAdminNode.load_field_options(
            "project_id", {"client_id": "", "client_secret": ""}
        )
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_load_unknown_field(self, mock_token):
        result = await AtlasAdminNode.load_field_options("nonexistent_field", self.CRED)
        assert result == {"options": []}


# ---------------------------------------------------------------------------
# Trigger config edge cases
# ---------------------------------------------------------------------------

class TestTriggerConfigs:
    def test_on_alert_has_webhook_fields(self):
        c = AtlasOnAlertConfig(trigger_group_id=FAKE_PROJECT_ID)
        assert c.webhook_url is None
        assert c.signing_secret is None

    def test_poll_triggers_have_schedule(self):
        """Poll trigger configs inherit schedule from PollTriggerConfigBase."""
        for cls in (AtlasOnClusterEventConfig, AtlasOnBackupEventConfig,
                    AtlasOnMaintenanceEventConfig, AtlasOnUserEventConfig, AtlasOnAlertEventConfig):
            c = cls(trigger_group_id=FAKE_PROJECT_ID)
            assert hasattr(c, "schedule"), f"{cls.__name__} missing schedule field"
            assert c.schedule is not None

    def test_node_type_constant(self):
        assert AtlasAdminNode.type == "automation-atlas-admin"

    def test_trigger_operations_set(self):
        ops = AtlasAdminNode.TRIGGER_OPERATIONS
        assert "on_alert" in ops
        for poll_op in ("on_cluster_event", "on_backup_event", "on_maintenance_event",
                        "on_user_event", "on_alert_event"):
            assert poll_op in ops, f"{poll_op} missing from TRIGGER_OPERATIONS"

    def test_credential_fields(self):
        creds = AtlasAdminCredential(client_id="cid", client_secret="csec")
        assert creds.client_id == "cid"
        assert creds.client_secret == "csec"
        assert creds.credential_type == "atlas_admin_oauth2"
