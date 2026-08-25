"""
Mock unit tests for Cloudflare REST API node.

Run: pytest backend/nodes/tests/test_cloudflare_node.py

No real API calls — all HTTP requests are mocked. Safe to run without credentials.
"""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from nodes.cloudflare_node import (
    CloudflareNode,
    CloudflareNodeConfig,
    CloudflareAPITokenCredential,
    CloudflareAPIKeyCredential,
    # DNS
    CloudflareListDNSRecordsConfig,
    CloudflareCreateDNSRecordConfig,
    CloudflareGetDNSRecordConfig,
    CloudflareUpdateDNSRecordConfig,
    CloudflareDeleteDNSRecordConfig,
    # Zones
    CloudflareListZonesConfig,
    CloudflareGetZoneConfig,
    CloudflareGetZoneSettingsConfig,
    CloudflareUpdateZoneSettingConfig,
    CloudflarePurgeZoneCacheConfig,
    # Workers
    CloudflareListWorkersConfig,
    CloudflareGetWorkerConfig,
    CloudflareUploadWorkerConfig,
    CloudflareDeleteWorkerConfig,
    CloudflareListWorkerRoutesConfig,
    CloudflareCreateWorkerRouteConfig,
    CloudflareDeleteWorkerRouteConfig,
    # Workers KV
    CloudflareListKVNamespacesConfig,
    CloudflareCreateKVNamespaceConfig,
    CloudflareDeleteKVNamespaceConfig,
    CloudflareListKVKeysConfig,
    CloudflareReadKVValueConfig,
    CloudflareWriteKVValueConfig,
    CloudflareDeleteKVValueConfig,
    CloudflareBulkWriteKVConfig,
    # D1
    CloudflareListD1DatabasesConfig,
    CloudflareGetD1DatabaseConfig,
    CloudflareCreateD1DatabaseConfig,
    CloudflareDeleteD1DatabaseConfig,
    CloudflareQueryD1DatabaseConfig,
    CloudflareExportD1DatabaseConfig,
    # R2
    CloudflareListR2BucketsConfig,
    CloudflareGetR2BucketConfig,
    CloudflareCreateR2BucketConfig,
    CloudflareDeleteR2BucketConfig,
    # Pages
    CloudflareListPagesProjectsConfig,
    CloudflareGetPagesProjectConfig,
    CloudflareDeletePagesProjectConfig,
    CloudflareListPagesDeploymentsConfig,
    CloudflareGetPagesDeploymentConfig,
    CloudflareDeletePagesDeploymentConfig,
    # Stream
    CloudflareListStreamVideosConfig,
    CloudflareGetStreamVideoConfig,
    CloudflareDeleteStreamVideoConfig,
    CloudflareGetStreamVideoEmbedConfig,
    CloudflareListStreamLiveInputsConfig,
    CloudflareCreateStreamLiveInputConfig,
    CloudflareDeleteStreamLiveInputConfig,
    # Images
    CloudflareListImagesConfig,
    CloudflareGetImageConfig,
    CloudflareDeleteImageConfig,
    CloudflareGetImagesStatsConfig,
    CloudflareCreateImageDirectUploadConfig,
    # Firewall / WAF
    CloudflareListFirewallRulesConfig,
    CloudflareCreateFirewallRuleConfig,
    CloudflareDeleteFirewallRuleConfig,
    CloudflareListWAFPackagesConfig,
    # Access
    CloudflareListAccessApplicationsConfig,
    CloudflareGetAccessApplicationConfig,
    CloudflareCreateAccessApplicationConfig,
    CloudflareDeleteAccessApplicationConfig,
    CloudflareListAccessPoliciesConfig,
    # Tunnels
    CloudflareListTunnelsConfig,
    CloudflareGetTunnelConfig,
    CloudflareCreateTunnelConfig,
    CloudflareDeleteTunnelConfig,
    CloudflareGetTunnelTokenConfig,
    # Email Routing
    CloudflareGetEmailRoutingConfig,
    CloudflareListEmailRoutingRulesConfig,
    CloudflareCreateEmailRoutingRuleConfig,
    CloudflareDeleteEmailRoutingRuleConfig,
    CloudflareListEmailRoutingAddressesConfig,
    # Queues
    CloudflareListQueuesConfig,
    CloudflareGetQueueConfig,
    CloudflareCreateQueueConfig,
    CloudflareDeleteQueueConfig,
    CloudflareSendQueueMessageConfig,
    CloudflarePullQueueMessagesConfig,
    # Workers AI
    CloudflareRunAIModelConfig,
    CloudflareListAIModelsConfig,
    # Vectorize
    CloudflareListVectorizeIndexesConfig,
    CloudflareGetVectorizeIndexConfig,
    CloudflareCreateVectorizeIndexConfig,
    CloudflareDeleteVectorizeIndexConfig,
    CloudflareUpsertVectorsConfig,
    CloudflareQueryVectorsConfig,
    CloudflareDeleteVectorsConfig,
    # Load Balancing
    CloudflareListLoadBalancersConfig,
    CloudflareGetLoadBalancerConfig,
    CloudflareCreateLoadBalancerConfig,
    CloudflareDeleteLoadBalancerConfig,
    CloudflareListLBPoolsConfig,
    CloudflareCreateLBPoolConfig,
    # SSL
    CloudflareGetSSLSettingsConfig,
    CloudflareListSSLCertificatesConfig,
    # Analytics
    CloudflareGetZoneAnalyticsConfig,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def token_cred():
    return CloudflareAPITokenCredential(
        api_token="test_api_token_123",
        account_id="test_account_id_456",
    )


@pytest.fixture
def api_key_cred():
    return CloudflareAPIKeyCredential(
        api_key="test_global_api_key",
        email="test@example.com",
        account_id="test_account_id_456",
    )


def make_node(config, creds=None) -> CloudflareNode:
    """Create a CloudflareNode with the given config pre-parsed."""
    node = CloudflareNode.__new__(CloudflareNode)
    if config is None:
        node._config = None
    else:
        node._config = CloudflareNodeConfig(config=config, credentials=creds)
    return node


def cf_success(result=None):
    """Build a standard Cloudflare success response."""
    return {"success": True, "result": result, "errors": [], "messages": []}


def cf_error(message="Test error"):
    """Build a standard Cloudflare error response."""
    return {
        "success": False,
        "result": None,
        "errors": [{"message": message}],
        "messages": [],
    }


def mock_cf_response(data: dict, status_code: int = 200):
    """Create a mock httpx response with a JSON body."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data)
    return resp


class MockAsyncClient:
    """Async context manager that returns a configured mock httpx client."""

    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        client = AsyncMock()
        client.request = AsyncMock(return_value=self._response)
        client.get = AsyncMock(return_value=self._response)
        client.post = AsyncMock(return_value=self._response)
        client.put = AsyncMock(return_value=self._response)
        client.delete = AsyncMock(return_value=self._response)
        client.patch = AsyncMock(return_value=self._response)
        return client

    async def __aexit__(self, *args):
        pass


async def run_node(config, creds, mock_result=None, status_code=200):
    """Helper: run node execute() with a mocked HTTP response."""
    node = make_node(config, creds)
    response = mock_cf_response(cf_success(mock_result), status_code)
    with patch("httpx.AsyncClient", return_value=MockAsyncClient(response)):
        return await node.execute({})


# ─── Credential Header Tests ───────────────────────────────────────────────────


class TestCredentialHeaders:
    def test_api_token_headers(self, token_cred):
        node = make_node(None)
        headers = node._get_headers(token_cred)
        assert headers["Authorization"] == "Bearer test_api_token_123"
        assert "X-Auth-Key" not in headers

    def test_api_key_headers(self, api_key_cred):
        node = make_node(None)
        headers = node._get_headers(api_key_cred)
        assert headers["X-Auth-Key"] == "test_global_api_key"
        assert headers["X-Auth-Email"] == "test@example.com"
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_account_path_with_id(self, token_cred):
        node = make_node(None)
        assert await node._account_path(token_cred) == "/accounts/test_account_id_456"

    @pytest.mark.asyncio
    async def test_account_path_without_id_raises(self):
        cred = CloudflareAPITokenCredential(api_token="tok")
        node = make_node(None)
        with pytest.raises(ValueError):
            await node._account_path(cred)


# ─── DNS Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDNS:
    async def test_list_dns_records(self, token_cred):
        config = CloudflareListDNSRecordsConfig(zone_id="zone123")
        result = await run_node(config, token_cred, [{"id": "rec1", "type": "A"}])
        assert result["status"] == "success"
        assert result["action"] == "list_dns_records"

    async def test_list_dns_records_with_filter(self, token_cred):
        config = CloudflareListDNSRecordsConfig(
            zone_id="zone123", record_type="A", name="example.com"
        )
        result = await run_node(config, token_cred, [])
        assert result["status"] == "success"

    async def test_create_dns_record(self, token_cred):
        config = CloudflareCreateDNSRecordConfig(
            zone_id="zone123",
            record_type="A",
            name="api.example.com",
            content="1.2.3.4",
            proxied="true",
        )
        result = await run_node(config, token_cred, {"id": "newrec", "type": "A"})
        assert result["status"] == "success"
        assert result["action"] == "create_dns_record"

    async def test_get_dns_record(self, token_cred):
        config = CloudflareGetDNSRecordConfig(zone_id="zone123", record_id="rec1")
        result = await run_node(config, token_cred, {"id": "rec1"})
        assert result["status"] == "success"
        assert result["action"] == "get_dns_record"

    async def test_update_dns_record(self, token_cred):
        config = CloudflareUpdateDNSRecordConfig(
            zone_id="zone123", record_id="rec1", content="5.6.7.8"
        )
        result = await run_node(
            config, token_cred, {"id": "rec1", "content": "5.6.7.8"}
        )
        assert result["status"] == "success"
        assert result["action"] == "update_dns_record"

    async def test_delete_dns_record(self, token_cred):
        config = CloudflareDeleteDNSRecordConfig(zone_id="zone123", record_id="rec1")
        result = await run_node(config, token_cred, {"id": "rec1"})
        assert result["status"] == "success"
        assert result["action"] == "delete_dns_record"


# ─── Zone Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestZones:
    async def test_list_zones(self, token_cred):
        config = CloudflareListZonesConfig()
        result = await run_node(
            config, token_cred, [{"id": "zone1", "name": "example.com"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_zones"

    async def test_get_zone(self, token_cred):
        config = CloudflareGetZoneConfig(zone_id="zone123")
        result = await run_node(
            config, token_cred, {"id": "zone123", "name": "example.com"}
        )
        assert result["status"] == "success"
        assert result["action"] == "get_zone"

    async def test_get_zone_settings(self, token_cred):
        config = CloudflareGetZoneSettingsConfig(zone_id="zone123")
        result = await run_node(
            config, token_cred, [{"id": "ssl", "value": "flexible"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "get_zone_settings"

    async def test_update_zone_setting(self, token_cred):
        config = CloudflareUpdateZoneSettingConfig(
            zone_id="zone123", setting_id="ssl", value="full"
        )
        result = await run_node(config, token_cred, {"id": "ssl", "value": "full"})
        assert result["status"] == "success"
        assert result["action"] == "update_zone_setting"

    async def test_purge_cache_all(self, token_cred):
        config = CloudflarePurgeZoneCacheConfig(zone_id="zone123", purge_all="true")
        result = await run_node(config, token_cred, {"id": "zone123"})
        assert result["status"] == "success"
        assert result["action"] == "purge_zone_cache"

    async def test_purge_cache_by_urls(self, token_cred):
        config = CloudflarePurgeZoneCacheConfig(
            zone_id="zone123",
            purge_all="false",
            files="https://example.com/page1,https://example.com/page2",
        )
        result = await run_node(config, token_cred, {"id": "zone123"})
        assert result["status"] == "success"


# ─── Workers Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestWorkers:
    async def test_list_workers(self, token_cred):
        config = CloudflareListWorkersConfig()
        result = await run_node(config, token_cred, [{"id": "worker1"}])
        assert result["status"] == "success"
        assert result["action"] == "list_workers"

    async def test_get_worker(self, token_cred):
        config = CloudflareGetWorkerConfig(script_name="my-worker")
        result = await run_node(config, token_cred, {"id": "my-worker"})
        assert result["status"] == "success"
        assert result["action"] == "get_worker"

    async def test_upload_worker(self, token_cred):
        config = CloudflareUploadWorkerConfig(
            script_name="my-worker",
            script_content="export default { fetch(req) { return new Response('Hello'); } }",
        )
        node = make_node(config, token_cred)
        response = mock_cf_response(cf_success({"id": "my-worker"}))
        with patch("httpx.AsyncClient", return_value=MockAsyncClient(response)):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upload_worker_script"

    async def test_delete_worker(self, token_cred):
        config = CloudflareDeleteWorkerConfig(script_name="my-worker")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_worker"

    async def test_list_worker_routes(self, token_cred):
        config = CloudflareListWorkerRoutesConfig(zone_id="zone123")
        result = await run_node(
            config, token_cred, [{"id": "route1", "pattern": "example.com/*"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_worker_routes"

    async def test_create_worker_route(self, token_cred):
        config = CloudflareCreateWorkerRouteConfig(
            zone_id="zone123",
            pattern="example.com/api/*",
            script_name="my-worker",
        )
        result = await run_node(config, token_cred, {"id": "route1"})
        assert result["status"] == "success"
        assert result["action"] == "create_worker_route"

    async def test_delete_worker_route(self, token_cred):
        config = CloudflareDeleteWorkerRouteConfig(zone_id="zone123", route_id="route1")
        result = await run_node(config, token_cred, {"id": "route1"})
        assert result["status"] == "success"
        assert result["action"] == "delete_worker_route"


# ─── Workers KV Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestWorkersKV:
    async def test_list_kv_namespaces(self, token_cred):
        config = CloudflareListKVNamespacesConfig()
        result = await run_node(config, token_cred, [{"id": "ns1", "title": "MY_KV"}])
        assert result["status"] == "success"
        assert result["action"] == "list_kv_namespaces"

    async def test_create_kv_namespace(self, token_cred):
        config = CloudflareCreateKVNamespaceConfig(title="MY_NEW_KV")
        result = await run_node(config, token_cred, {"id": "ns2", "title": "MY_NEW_KV"})
        assert result["status"] == "success"
        assert result["action"] == "create_kv_namespace"

    async def test_delete_kv_namespace(self, token_cred):
        config = CloudflareDeleteKVNamespaceConfig(namespace_id="ns1")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_kv_namespace"

    async def test_list_kv_keys(self, token_cred):
        config = CloudflareListKVKeysConfig(namespace_id="ns1", prefix="user:")
        result = await run_node(config, token_cred, [{"name": "user:123"}])
        assert result["status"] == "success"
        assert result["action"] == "list_kv_keys"

    async def test_read_kv_value(self, token_cred):
        config = CloudflareReadKVValueConfig(namespace_id="ns1", key_name="my-key")
        node = make_node(config, token_cred)
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "hello world"
        with patch("httpx.AsyncClient", return_value=MockAsyncClient(resp)):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["value"] == "hello world"
        assert result["action"] == "read_kv_value"

    async def test_write_kv_value(self, token_cred):
        config = CloudflareWriteKVValueConfig(
            namespace_id="ns1", key_name="my-key", value="my-value"
        )
        node = make_node(config, token_cred)
        resp = mock_cf_response(cf_success(None))
        with patch("httpx.AsyncClient", return_value=MockAsyncClient(resp)):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "write_kv_value"

    async def test_delete_kv_value(self, token_cred):
        config = CloudflareDeleteKVValueConfig(namespace_id="ns1", key_name="my-key")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_kv_value"

    async def test_bulk_write_kv(self, token_cred):
        config = CloudflareBulkWriteKVConfig(
            namespace_id="ns1",
            pairs='[{"key": "k1", "value": "v1"}, {"key": "k2", "value": "v2"}]',
        )
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "bulk_write_kv_pairs"

    async def test_bulk_write_kv_invalid_json(self, token_cred):
        config = CloudflareBulkWriteKVConfig(namespace_id="ns1", pairs="not-json")
        node = make_node(config, token_cred)
        result = await node.execute({})
        assert result["status"] == "error"
        assert "Invalid JSON" in result["error"]


# ─── D1 Database Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestD1Database:
    async def test_list_d1_databases(self, token_cred):
        config = CloudflareListD1DatabasesConfig()
        result = await run_node(config, token_cred, [{"uuid": "db1", "name": "mydb"}])
        assert result["status"] == "success"
        assert result["action"] == "list_d1_databases"

    async def test_get_d1_database(self, token_cred):
        config = CloudflareGetD1DatabaseConfig(database_id="db1")
        result = await run_node(config, token_cred, {"uuid": "db1"})
        assert result["status"] == "success"
        assert result["action"] == "get_d1_database"

    async def test_create_d1_database(self, token_cred):
        config = CloudflareCreateD1DatabaseConfig(name="mydb", location="weur")
        result = await run_node(config, token_cred, {"uuid": "db2", "name": "mydb"})
        assert result["status"] == "success"
        assert result["action"] == "create_d1_database"

    async def test_delete_d1_database(self, token_cred):
        config = CloudflareDeleteD1DatabaseConfig(database_id="db1")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_d1_database"

    async def test_query_d1_database(self, token_cred):
        config = CloudflareQueryD1DatabaseConfig(
            database_id="db1",
            sql="SELECT * FROM users LIMIT 10",
        )
        result = await run_node(
            config, token_cred, [{"results": [{"id": 1}], "success": True}]
        )
        assert result["status"] == "success"
        assert result["action"] == "execute_d1_sql_query"

    async def test_query_d1_with_params(self, token_cred):
        config = CloudflareQueryD1DatabaseConfig(
            database_id="db1",
            sql="SELECT * FROM users WHERE id = ?",
            params="[42]",
        )
        result = await run_node(config, token_cred, [{"results": [], "success": True}])
        assert result["status"] == "success"

    async def test_query_d1_invalid_params(self, token_cred):
        config = CloudflareQueryD1DatabaseConfig(
            database_id="db1",
            sql="SELECT 1",
            params="not-json",
        )
        node = make_node(config, token_cred)
        result = await node.execute({})
        assert result["status"] == "error"

    async def test_export_d1_database(self, token_cred):
        config = CloudflareExportD1DatabaseConfig(database_id="db1")
        result = await run_node(
            config, token_cred, {"filename": "db1.sql", "status": "complete"}
        )
        assert result["status"] == "success"
        assert result["action"] == "export_d1_database_as_sql"


# ─── R2 Storage Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestR2Storage:
    async def test_list_r2_buckets(self, token_cred):
        config = CloudflareListR2BucketsConfig()
        result = await run_node(
            config, token_cred, {"buckets": [{"name": "my-bucket"}]}
        )
        assert result["status"] == "success"
        assert result["action"] == "list_r2_buckets"

    async def test_get_r2_bucket(self, token_cred):
        config = CloudflareGetR2BucketConfig(bucket_name="my-bucket")
        result = await run_node(config, token_cred, {"name": "my-bucket"})
        assert result["status"] == "success"
        assert result["action"] == "get_r2_bucket"

    async def test_create_r2_bucket(self, token_cred):
        config = CloudflareCreateR2BucketConfig(
            bucket_name="new-bucket", location_hint="wnam"
        )
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "create_r2_bucket"

    async def test_delete_r2_bucket(self, token_cred):
        config = CloudflareDeleteR2BucketConfig(bucket_name="my-bucket")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_r2_bucket"

    # get_r2_bucket_usage was removed from the node (dead Cloudflare endpoint);
    # its import + test were removed with it.


# ─── Pages Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPages:
    async def test_list_pages_projects(self, token_cred):
        config = CloudflareListPagesProjectsConfig()
        result = await run_node(config, token_cred, [{"name": "my-site"}])
        assert result["status"] == "success"
        assert result["action"] == "list_pages_projects"

    async def test_get_pages_project(self, token_cred):
        config = CloudflareGetPagesProjectConfig(project_name="my-site")
        result = await run_node(config, token_cred, {"name": "my-site"})
        assert result["status"] == "success"
        assert result["action"] == "get_pages_project"

    async def test_delete_pages_project(self, token_cred):
        config = CloudflareDeletePagesProjectConfig(project_name="my-site")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_pages_project"

    async def test_list_pages_deployments(self, token_cred):
        config = CloudflareListPagesDeploymentsConfig(project_name="my-site")
        result = await run_node(
            config, token_cred, [{"id": "dep1", "environment": "production"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_pages_deployments"

    async def test_get_pages_deployment(self, token_cred):
        config = CloudflareGetPagesDeploymentConfig(
            project_name="my-site", deployment_id="dep1"
        )
        result = await run_node(config, token_cred, {"id": "dep1"})
        assert result["status"] == "success"
        assert result["action"] == "get_pages_deployment"

    async def test_delete_pages_deployment(self, token_cred):
        config = CloudflareDeletePagesDeploymentConfig(
            project_name="my-site", deployment_id="dep1"
        )
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_pages_deployment"


# ─── Stream Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestStream:
    async def test_list_stream_videos(self, token_cred):
        config = CloudflareListStreamVideosConfig()
        result = await run_node(
            config, token_cred, [{"uid": "vid1", "status": {"state": "ready"}}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_stream_videos"

    async def test_get_stream_video(self, token_cred):
        config = CloudflareGetStreamVideoConfig(video_id="vid1")
        result = await run_node(config, token_cred, {"uid": "vid1"})
        assert result["status"] == "success"
        assert result["action"] == "get_stream_video"

    async def test_delete_stream_video(self, token_cred):
        config = CloudflareDeleteStreamVideoConfig(video_id="vid1")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_stream_video"

    async def test_get_stream_embed(self, token_cred):
        config = CloudflareGetStreamVideoEmbedConfig(video_id="vid1", autoplay="true")
        result = await run_node(config, token_cred, "<iframe src='...'></iframe>")
        assert result["status"] == "success"
        assert result["action"] == "get_stream_video_embed_code"

    async def test_list_stream_live_inputs(self, token_cred):
        config = CloudflareListStreamLiveInputsConfig()
        result = await run_node(config, token_cred, [{"uid": "live1"}])
        assert result["status"] == "success"
        assert result["action"] == "list_stream_live_inputs"

    async def test_create_stream_live_input(self, token_cred):
        config = CloudflareCreateStreamLiveInputConfig(
            name="My Stream", recording_mode="automatic"
        )
        result = await run_node(config, token_cred, {"uid": "live1"})
        assert result["status"] == "success"
        assert result["action"] == "create_stream_live_input"

    async def test_delete_stream_live_input(self, token_cred):
        config = CloudflareDeleteStreamLiveInputConfig(live_input_id="live1")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_stream_live_input"


# ─── Images Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestImages:
    async def test_list_images(self, token_cred):
        config = CloudflareListImagesConfig()
        result = await run_node(config, token_cred, {"images": [{"id": "img1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_images"

    async def test_get_image(self, token_cred):
        config = CloudflareGetImageConfig(image_id="img1")
        result = await run_node(config, token_cred, {"id": "img1"})
        assert result["status"] == "success"
        assert result["action"] == "get_image"

    async def test_delete_image(self, token_cred):
        config = CloudflareDeleteImageConfig(image_id="img1")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_image"

    async def test_get_images_stats(self, token_cred):
        config = CloudflareGetImagesStatsConfig()
        result = await run_node(
            config, token_cred, {"count": {"current": 100, "allowed": 100000}}
        )
        assert result["status"] == "success"
        assert result["action"] == "get_image_usage_statistics"

    async def test_create_image_direct_upload(self, token_cred):
        config = CloudflareCreateImageDirectUploadConfig(require_signed_urls="false")
        result = await run_node(
            config,
            token_cred,
            {"id": "img2", "uploadURL": "https://upload.imagedelivery.net/..."},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_image_direct_upload_url"


# ─── Firewall / WAF Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestFirewall:
    async def test_list_firewall_rules(self, token_cred):
        config = CloudflareListFirewallRulesConfig(zone_id="zone123")
        result = await run_node(
            config, token_cred, [{"id": "rule1", "action": "block"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_firewall_rules"

    async def test_create_firewall_rule(self, token_cred):
        config = CloudflareCreateFirewallRuleConfig(
            zone_id="zone123",
            expression="ip.src eq 1.2.3.4",
            rule_action="block",
            description="Block bad IP",
        )
        result = await run_node(config, token_cred, [{"id": "rule2"}])
        assert result["status"] == "success"
        assert result["action"] == "create_firewall_rule"

    async def test_delete_firewall_rule(self, token_cred):
        config = CloudflareDeleteFirewallRuleConfig(zone_id="zone123", rule_id="rule1")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_firewall_rule"

    async def test_list_waf_packages(self, token_cred):
        config = CloudflareListWAFPackagesConfig(zone_id="zone123")
        result = await run_node(
            config, token_cred, [{"id": "pkg1", "name": "Cloudflare Managed"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_zone_waf_packages"


# ─── Access (Zero Trust) Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAccess:
    async def test_list_access_applications(self, token_cred):
        config = CloudflareListAccessApplicationsConfig()
        result = await run_node(config, token_cred, [{"id": "app1", "name": "My App"}])
        assert result["status"] == "success"
        assert result["action"] == "list_access_applications"

    async def test_get_access_application(self, token_cred):
        config = CloudflareGetAccessApplicationConfig(app_id="app1")
        result = await run_node(config, token_cred, {"id": "app1"})
        assert result["status"] == "success"
        assert result["action"] == "get_access_application"

    async def test_create_access_application(self, token_cred):
        config = CloudflareCreateAccessApplicationConfig(
            name="Internal App",
            domain="internal.example.com",
            app_type="self_hosted",
        )
        result = await run_node(config, token_cred, {"id": "app2"})
        assert result["status"] == "success"
        assert result["action"] == "create_access_application"

    async def test_delete_access_application(self, token_cred):
        config = CloudflareDeleteAccessApplicationConfig(app_id="app1")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_access_application"

    async def test_list_access_policies(self, token_cred):
        config = CloudflareListAccessPoliciesConfig(app_id="app1")
        result = await run_node(config, token_cred, [{"id": "pol1"}])
        assert result["status"] == "success"
        assert result["action"] == "list_access_application_policies"


# ─── Tunnels Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestTunnels:
    async def test_list_tunnels(self, token_cred):
        config = CloudflareListTunnelsConfig()
        result = await run_node(
            config, token_cred, [{"id": "tun1", "name": "my-tunnel"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_tunnels"

    async def test_get_tunnel(self, token_cred):
        config = CloudflareGetTunnelConfig(tunnel_id="tun1")
        result = await run_node(config, token_cred, {"id": "tun1"})
        assert result["status"] == "success"
        assert result["action"] == "get_tunnel"

    async def test_create_tunnel(self, token_cred):
        config = CloudflareCreateTunnelConfig(name="new-tunnel")
        result = await run_node(
            config, token_cred, {"id": "tun2", "name": "new-tunnel"}
        )
        assert result["status"] == "success"
        assert result["action"] == "create_tunnel"

    async def test_delete_tunnel(self, token_cred):
        config = CloudflareDeleteTunnelConfig(tunnel_id="tun1")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_tunnel"

    async def test_get_tunnel_token(self, token_cred):
        config = CloudflareGetTunnelTokenConfig(tunnel_id="tun1")
        result = await run_node(config, token_cred, "eyJ0dW5uZWxJRCI...")
        assert result["status"] == "success"
        assert result["action"] == "get_tunnel_token"


# ─── Email Routing Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestEmailRouting:
    async def test_get_email_routing(self, token_cred):
        config = CloudflareGetEmailRoutingConfig(zone_id="zone123")
        result = await run_node(config, token_cred, {"enabled": True})
        assert result["status"] == "success"
        assert result["action"] == "get_email_routing_settings"

    async def test_list_email_routing_rules(self, token_cred):
        config = CloudflareListEmailRoutingRulesConfig(zone_id="zone123")
        result = await run_node(config, token_cred, [{"tag": "rule1"}])
        assert result["status"] == "success"
        assert result["action"] == "list_email_routing_rules"

    async def test_create_email_routing_rule(self, token_cred):
        config = CloudflareCreateEmailRoutingRuleConfig(
            zone_id="zone123",
            name="Forward to me",
            matchers='[{"type": "literal", "field": "to", "value": "info@example.com"}]',
            actions='[{"type": "forward", "value": ["me@personal.com"]}]',
        )
        result = await run_node(config, token_cred, {"tag": "rule2"})
        assert result["status"] == "success"
        assert result["action"] == "create_email_routing_rule"

    async def test_create_email_routing_rule_invalid_json(self, token_cred):
        config = CloudflareCreateEmailRoutingRuleConfig(
            zone_id="zone123",
            name="bad",
            matchers="not-json",
            actions="also-not-json",
        )
        node = make_node(config, token_cred)
        result = await node.execute({})
        assert result["status"] == "error"

    async def test_delete_email_routing_rule(self, token_cred):
        config = CloudflareDeleteEmailRoutingRuleConfig(
            zone_id="zone123", rule_id="rule1"
        )
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_email_routing_rule"

    async def test_list_email_routing_addresses(self, token_cred):
        config = CloudflareListEmailRoutingAddressesConfig()
        result = await run_node(config, token_cred, [{"email": "me@example.com"}])
        assert result["status"] == "success"
        assert result["action"] == "list_email_routing_destination_addresses"


# ─── Queues Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestQueues:
    async def test_list_queues(self, token_cred):
        config = CloudflareListQueuesConfig()
        result = await run_node(
            config, token_cred, [{"queue_id": "q1", "queue_name": "my-queue"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_queues"

    async def test_get_queue(self, token_cred):
        config = CloudflareGetQueueConfig(queue_id="q1")
        result = await run_node(config, token_cred, {"queue_id": "q1"})
        assert result["status"] == "success"
        assert result["action"] == "get_queue"

    async def test_create_queue(self, token_cred):
        config = CloudflareCreateQueueConfig(queue_name="new-queue")
        result = await run_node(
            config, token_cred, {"queue_id": "q2", "queue_name": "new-queue"}
        )
        assert result["status"] == "success"
        assert result["action"] == "create_queue"

    async def test_delete_queue(self, token_cred):
        config = CloudflareDeleteQueueConfig(queue_id="q1")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_queue"

    async def test_send_queue_message(self, token_cred):
        config = CloudflareSendQueueMessageConfig(
            queue_id="q1",
            body='{"event": "user_signup"}',
            content_type="json",
        )
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "send_queue_message"

    async def test_pull_queue_messages(self, token_cred):
        config = CloudflarePullQueueMessagesConfig(queue_id="q1", batch_size=10)
        result = await run_node(
            config, token_cred, {"messages": [{"id": "msg1", "body": "hello"}]}
        )
        assert result["status"] == "success"
        assert result["action"] == "pull_queue_messages"


# ─── Workers AI Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestWorkersAI:
    async def test_run_ai_model(self, token_cred):
        config = CloudflareRunAIModelConfig(
            model_name="@cf/meta/llama-3.1-8b-instruct",
            input_data='{"messages": [{"role": "user", "content": "Hello"}]}',
        )
        result = await run_node(config, token_cred, {"response": "Hi there!"})
        assert result["status"] == "success"
        assert result["action"] == "run_workers_ai_inference"

    async def test_run_ai_model_invalid_json(self, token_cred):
        config = CloudflareRunAIModelConfig(
            model_name="@cf/meta/llama-3.1-8b-instruct",
            input_data="not-json",
        )
        node = make_node(config, token_cred)
        result = await node.execute({})
        assert result["status"] == "error"

    async def test_list_ai_models(self, token_cred):
        config = CloudflareListAIModelsConfig(task="Text Generation")
        result = await run_node(
            config, token_cred, [{"name": "@cf/meta/llama-3.1-8b-instruct"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_workers_ai_models"


# ─── Vectorize Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestVectorize:
    async def test_list_vectorize_indexes(self, token_cred):
        config = CloudflareListVectorizeIndexesConfig()
        result = await run_node(config, token_cred, [{"name": "my-index"}])
        assert result["status"] == "success"
        assert result["action"] == "list_vectorize_indexes"

    async def test_get_vectorize_index(self, token_cred):
        config = CloudflareGetVectorizeIndexConfig(index_name="my-index")
        result = await run_node(config, token_cred, {"name": "my-index"})
        assert result["status"] == "success"
        assert result["action"] == "get_vectorize_index"

    async def test_create_vectorize_index(self, token_cred):
        config = CloudflareCreateVectorizeIndexConfig(
            name="embeddings",
            dimensions=1536,
            metric="cosine",
        )
        result = await run_node(config, token_cred, {"name": "embeddings"})
        assert result["status"] == "success"
        assert result["action"] == "create_vectorize_index"

    async def test_delete_vectorize_index(self, token_cred):
        config = CloudflareDeleteVectorizeIndexConfig(index_name="my-index")
        result = await run_node(config, token_cred, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_vectorize_index"

    async def test_upsert_vectors(self, token_cred):
        config = CloudflareUpsertVectorsConfig(
            index_name="my-index",
            vectors='[{"id": "v1", "values": [0.1, 0.2, 0.3]}]',
        )
        node = make_node(config, token_cred)
        response = mock_cf_response(cf_success({"count": 1, "mutationId": "mut1"}))
        with patch("httpx.AsyncClient", return_value=MockAsyncClient(response)):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upsert_vectors_to_index"

    async def test_query_vectors(self, token_cred):
        config = CloudflareQueryVectorsConfig(
            index_name="my-index",
            query_vector="[0.1, 0.2, 0.3]",
            top_k=5,
        )
        result = await run_node(
            config, token_cred, {"matches": [{"id": "v1", "score": 0.99}]}
        )
        assert result["status"] == "success"
        assert result["action"] == "query_vectorize_index"

    async def test_delete_vectors(self, token_cred):
        config = CloudflareDeleteVectorsConfig(
            index_name="my-index", vector_ids="v1,v2,v3"
        )
        result = await run_node(config, token_cred, {"count": 3, "mutationId": "mut2"})
        assert result["status"] == "success"
        assert result["action"] == "delete_vectors_from_index"


# ─── Load Balancing Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLoadBalancing:
    async def test_list_load_balancers(self, token_cred):
        config = CloudflareListLoadBalancersConfig(zone_id="zone123")
        result = await run_node(
            config, token_cred, [{"id": "lb1", "name": "api.example.com"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_load_balancers"

    async def test_get_load_balancer(self, token_cred):
        config = CloudflareGetLoadBalancerConfig(zone_id="zone123", lb_id="lb1")
        result = await run_node(config, token_cred, {"id": "lb1"})
        assert result["status"] == "success"
        assert result["action"] == "get_load_balancer"

    async def test_create_load_balancer(self, token_cred):
        config = CloudflareCreateLoadBalancerConfig(
            zone_id="zone123",
            name="api.example.com",
            default_pools='["pool1", "pool2"]',
            fallback_pool="pool1",
        )
        result = await run_node(config, token_cred, {"id": "lb2"})
        assert result["status"] == "success"
        assert result["action"] == "create_load_balancer"

    async def test_delete_load_balancer(self, token_cred):
        config = CloudflareDeleteLoadBalancerConfig(zone_id="zone123", lb_id="lb1")
        result = await run_node(config, token_cred, {"id": "lb1"})
        assert result["status"] == "success"
        assert result["action"] == "delete_load_balancer"

    async def test_list_lb_pools(self, token_cred):
        config = CloudflareListLBPoolsConfig()
        result = await run_node(
            config, token_cred, [{"id": "pool1", "name": "us-east"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_load_balancer_pools"

    async def test_create_lb_pool(self, token_cred):
        config = CloudflareCreateLBPoolConfig(
            name="us-east",
            origins='[{"name": "web-1", "address": "1.2.3.4", "enabled": true}]',
        )
        result = await run_node(config, token_cred, {"id": "pool2"})
        assert result["status"] == "success"
        assert result["action"] == "create_load_balancer_pool"


# ─── SSL / TLS Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestSSL:
    async def test_get_ssl_settings(self, token_cred):
        config = CloudflareGetSSLSettingsConfig(zone_id="zone123")
        result = await run_node(config, token_cred, {"id": "ssl", "value": "flexible"})
        assert result["status"] == "success"
        assert result["action"] == "get_zone_ssl_settings"

    async def test_list_ssl_certificates(self, token_cred):
        config = CloudflareListSSLCertificatesConfig(zone_id="zone123")
        result = await run_node(
            config, token_cred, [{"id": "cert1", "status": "active"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_zone_ssl_certificates"


# ─── Analytics Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAnalytics:
    async def test_get_zone_analytics(self, token_cred):
        config = CloudflareGetZoneAnalyticsConfig(zone_id="zone123")
        result = await run_node(
            config, token_cred, {"totals": {"requests": {"all": 10000}}}
        )
        assert result["status"] == "success"
        assert result["action"] == "get_zone_analytics"

    # get_account_analytics was removed from the node (moved to GraphQL / dead
    # REST endpoint); its import + test were removed with it.


# ─── Error Handling Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestErrorHandling:
    async def test_api_error_returns_status_error(self, token_cred):
        """API errors return {'status': 'error'}, not exceptions."""
        config = CloudflareListZonesConfig()
        node = make_node(config, token_cred)
        error_response = mock_cf_response(cf_error("Authentication error"), 403)
        with patch("httpx.AsyncClient", return_value=MockAsyncClient(error_response)):
            result = await node.execute({})
        assert result["status"] == "error"
        assert "Authentication error" in result["error"]

    async def test_missing_credentials_returns_error(self):
        config = CloudflareListZonesConfig()
        node = make_node(config, None)  # no credentials
        result = await node.execute({})
        assert result["status"] == "error"
        assert "credentials" in result["error"].lower()

    async def test_no_config_returns_error(self, token_cred):
        node = make_node(None)
        result = await node.execute({})
        assert result["status"] == "error"

    async def test_elapsed_ms_in_response(self, token_cred):
        config = CloudflareListZonesConfig()
        result = await run_node(config, token_cred, [])
        assert "elapsed_ms" in result
        assert isinstance(result["elapsed_ms"], float)

    async def test_api_key_credential_also_works(self, api_key_cred):
        """Legacy API key + email credential is also accepted."""
        config = CloudflareListZonesConfig()
        result = await run_node(config, api_key_cred, [])
        assert result["status"] == "success"

    async def test_account_required_for_workers(self):
        """Workers requires account_id in credentials."""
        cred = CloudflareAPITokenCredential(api_token="tok")  # no account_id
        config = CloudflareListWorkersConfig()
        node = make_node(config, cred)
        result = await node.execute({})
        assert result["status"] == "error"
        assert "account_id" in result["error"]
