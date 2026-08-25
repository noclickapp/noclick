"""
Mock tests for the Hex REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Runs: run project, get run status, get project runs, cancel run, get cell image
- Projects: list, get, update
- Sharing: collections, workspace/public, groups, users
- Embedding: create presigned URL
- Admin: list users, get me, deactivate user
- Groups: list, create, get, edit, delete
- Collections: list, create, get, edit
- Data connections: list, edit
- Semantic models: ingest
- Error handling: API errors, missing credentials, invalid JSON body
- Dynamic options: project dropdown
- Workspace host: custom single-tenant/EU host in the request URL
"""

import pytest
from unittest.mock import Mock, patch

from nodes.hex_node import (
    HexNode,
    HexNodeConfig,
    HexApiTokenCredential,
    HexRunProjectConfig,
    HexGetRunStatusConfig,
    HexGetProjectRunsConfig,
    HexCancelRunConfig,
    HexGetRunCellImageConfig,
    HexListProjectsConfig,
    HexGetProjectConfig,
    HexUpdateProjectConfig,
    HexUpdateProjectCollectionSharingConfig,
    HexUpdateProjectWorkspaceSharingConfig,
    HexUpdateProjectGroupSharingConfig,
    HexUpdateProjectUserSharingConfig,
    HexCreateEmbedUrlConfig,
    HexListUsersConfig,
    HexGetMeConfig,
    HexDeactivateUserConfig,
    HexListGroupsConfig,
    HexCreateGroupConfig,
    HexGetGroupConfig,
    HexEditGroupConfig,
    HexDeleteGroupConfig,
    HexListCollectionsConfig,
    HexCreateCollectionConfig,
    HexGetCollectionConfig,
    HexEditCollectionConfig,
    HexListDataConnectionsConfig,
    HexEditDataConnectionConfig,
    HexIngestSemanticProjectConfig,
    HexOnRunCompletedConfig,
)


@pytest.fixture
def api_credentials():
    return HexApiTokenCredential(api_token="hxtp_test_token_123")


def create_hex_node(config):
    return HexNode(
        node_id="test-hex-node",
        node_type="automation-hex",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, headers=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.content = b""
    mock_response.headers = headers if headers is not None else {"content-type": "application/json"}
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, headers=None, capture=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    works as an async context manager. Optionally capture call kwargs."""
    mock_response = create_mock_response(status_code, json_data, headers)
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


class TestHexRunsMock:
    @pytest.mark.asyncio
    async def test_run_project(self, api_credentials):
        config = HexNodeConfig(
            config=HexRunProjectConfig(
                project_id="proj-1",
                input_params='{"region": "EU"}',
                dry_run="false",
                update_published_results="false",
            ),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        capture = {}
        mock_client = create_mock_client(
            201, {"runId": "run-9", "runStatusUrl": "https://x", "projectStatusUrl": "https://y"},
            capture=capture,
        )
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "run_project"
        assert result["data"]["runId"] == "run-9"
        # input_params textarea parsed into inputParams dict
        assert capture["json"]["inputParams"] == {"region": "EU"}
        assert capture["json"]["dryRun"] is False

    @pytest.mark.asyncio
    async def test_get_run_status(self, api_credentials):
        config = HexNodeConfig(
            config=HexGetRunStatusConfig(project_id="proj-1", run_id="run-9"),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"status": "COMPLETED", "runId": "run-9"})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_run_status"
        assert result["data"]["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_get_project_runs(self, api_credentials):
        config = HexNodeConfig(
            config=HexGetProjectRunsConfig(project_id="proj-1", limit="10", status_filter="COMPLETED"),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"runs": [{"runId": "run-1"}]})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_project_runs"

    @pytest.mark.asyncio
    async def test_cancel_run(self, api_credentials):
        config = HexNodeConfig(
            config=HexCancelRunConfig(project_id="proj-1", run_id="run-9"),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "cancel_run"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_get_run_cell_image(self, api_credentials):
        config = HexNodeConfig(
            config=HexGetRunCellImageConfig(project_id="proj-1", run_id="run-9", static_id="cell-1"),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        mock_resp = create_mock_response(200, headers={"content-type": "image/png"})
        mock_resp.content = b"\x89PNG\r\n"
        mock_client = Mock()

        async def async_request(*args, **kwargs):
            return mock_resp

        mock_client.request = async_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_run_cell_image"
        from nodes.core.binary_output import BinaryOutput
        assert isinstance(result["data"], BinaryOutput)
        assert result["data"].content_type == "image/png"
        assert len(result["data"].data) == 6


class TestHexProjectsMock:
    @pytest.mark.asyncio
    async def test_list_projects(self, api_credentials):
        config = HexNodeConfig(
            config=HexListProjectsConfig(limit="50"), credentials=api_credentials
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"values": [{"id": "p1", "title": "Sales"}], "pagination": {"after": None}})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_projects"
        assert result["data"]["values"][0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_get_project(self, api_credentials):
        config = HexNodeConfig(
            config=HexGetProjectConfig(project_id="p1"), credentials=api_credentials
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"id": "p1", "title": "Sales"})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_project"
        assert result["data"]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_update_project(self, api_credentials):
        config = HexNodeConfig(
            config=HexUpdateProjectConfig(project_id="p1", body='{"status": {"name": "In review"}}'),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        capture = {}
        mock_client = create_mock_client(200, {"id": "p1"}, capture=capture)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_project"
        assert capture["json"]["status"]["name"] == "In review"


class TestHexSharingMock:
    @pytest.mark.asyncio
    async def test_update_collection_sharing(self, api_credentials):
        config = HexNodeConfig(
            config=HexUpdateProjectCollectionSharingConfig(project_id="p1", body='{"add": ["c1"]}'),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_collection_sharing"

    @pytest.mark.asyncio
    async def test_update_workspace_sharing(self, api_credentials):
        config = HexNodeConfig(
            config=HexUpdateProjectWorkspaceSharingConfig(project_id="p1", body='{"workspace": {"access": "CAN_VIEW"}}'),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_workspace_sharing"

    @pytest.mark.asyncio
    async def test_update_group_sharing(self, api_credentials):
        config = HexNodeConfig(
            config=HexUpdateProjectGroupSharingConfig(project_id="p1", body='{"add": [{"groupId": "g1", "access": "CAN_VIEW"}]}'),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_group_sharing"

    @pytest.mark.asyncio
    async def test_update_user_sharing(self, api_credentials):
        config = HexNodeConfig(
            config=HexUpdateProjectUserSharingConfig(project_id="p1", body='{"add": [{"userId": "u1", "access": "CAN_VIEW"}]}'),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_user_sharing"


class TestHexEmbeddingMock:
    @pytest.mark.asyncio
    async def test_create_embed_url(self, api_credentials):
        config = HexNodeConfig(
            config=HexCreateEmbedUrlConfig(
                project_id="p1",
                input_parameters='{"region": "EU"}',
                expires_in="300000",
                test_mode="true",
            ),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        capture = {}
        mock_client = create_mock_client(200, {"url": "https://app.hex.tech/embed/abc"}, capture=capture)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_embed_url"
        assert result["data"]["url"].startswith("https://")
        assert capture["json"]["expiresIn"] == 300000
        assert capture["json"]["testMode"] is True


class TestHexAdminMock:
    @pytest.mark.asyncio
    async def test_list_users(self, api_credentials):
        config = HexNodeConfig(config=HexListUsersConfig(limit="50"), credentials=api_credentials)
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"values": [{"id": "u1", "email": "a@b.com"}]})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_users"

    @pytest.mark.asyncio
    async def test_get_me(self, api_credentials):
        config = HexNodeConfig(config=HexGetMeConfig(), credentials=api_credentials)
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"id": "u1", "email": "me@hex.tech"})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_me"
        assert result["data"]["email"] == "me@hex.tech"

    @pytest.mark.asyncio
    async def test_deactivate_user(self, api_credentials):
        config = HexNodeConfig(
            config=HexDeactivateUserConfig(user_id="u1"), credentials=api_credentials
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "deactivate_user"


class TestHexGroupsMock:
    @pytest.mark.asyncio
    async def test_list_groups(self, api_credentials):
        config = HexNodeConfig(config=HexListGroupsConfig(), credentials=api_credentials)
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"values": [{"id": "g1", "name": "Analysts"}]})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_groups"

    @pytest.mark.asyncio
    async def test_create_group(self, api_credentials):
        config = HexNodeConfig(
            config=HexCreateGroupConfig(name="Analysts"), credentials=api_credentials
        )
        node = create_hex_node(config)
        capture = {}
        mock_client = create_mock_client(201, {"id": "g2", "name": "Analysts"}, capture=capture)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_group"
        assert capture["json"]["name"] == "Analysts"

    @pytest.mark.asyncio
    async def test_get_group(self, api_credentials):
        config = HexNodeConfig(config=HexGetGroupConfig(group_id="g1"), credentials=api_credentials)
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"id": "g1", "name": "Analysts"})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_group"
        assert result["data"]["id"] == "g1"

    @pytest.mark.asyncio
    async def test_edit_group(self, api_credentials):
        config = HexNodeConfig(
            config=HexEditGroupConfig(group_id="g1", body='{"name": "Renamed"}'),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        capture = {}
        mock_client = create_mock_client(200, {"id": "g1", "name": "Renamed"}, capture=capture)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "edit_group"
        assert capture["json"]["name"] == "Renamed"

    @pytest.mark.asyncio
    async def test_delete_group(self, api_credentials):
        config = HexNodeConfig(config=HexDeleteGroupConfig(group_id="g1"), credentials=api_credentials)
        node = create_hex_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_group"


class TestHexCollectionsMock:
    @pytest.mark.asyncio
    async def test_list_collections(self, api_credentials):
        config = HexNodeConfig(config=HexListCollectionsConfig(), credentials=api_credentials)
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"values": [{"id": "c1", "name": "Dashboards"}]})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_collections"

    @pytest.mark.asyncio
    async def test_create_collection(self, api_credentials):
        config = HexNodeConfig(
            config=HexCreateCollectionConfig(name="Dashboards", description="BI"),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        capture = {}
        mock_client = create_mock_client(201, {"id": "c2", "name": "Dashboards"}, capture=capture)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_collection"
        assert capture["json"]["name"] == "Dashboards"
        assert capture["json"]["description"] == "BI"

    @pytest.mark.asyncio
    async def test_get_collection(self, api_credentials):
        config = HexNodeConfig(
            config=HexGetCollectionConfig(collection_id="c1"), credentials=api_credentials
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"id": "c1", "name": "Dashboards"})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_collection"
        assert result["data"]["id"] == "c1"

    @pytest.mark.asyncio
    async def test_edit_collection(self, api_credentials):
        config = HexNodeConfig(
            config=HexEditCollectionConfig(collection_id="c1", body='{"name": "Renamed"}'),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        capture = {}
        mock_client = create_mock_client(200, {"id": "c1", "name": "Renamed"}, capture=capture)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "edit_collection"
        assert capture["json"]["name"] == "Renamed"


class TestHexDataConnectionsMock:
    @pytest.mark.asyncio
    async def test_list_data_connections(self, api_credentials):
        config = HexNodeConfig(config=HexListDataConnectionsConfig(), credentials=api_credentials)
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"values": [{"id": "dc1", "name": "Snowflake"}]})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_data_connections"

    @pytest.mark.asyncio
    async def test_edit_data_connection(self, api_credentials):
        config = HexNodeConfig(
            config=HexEditDataConnectionConfig(data_connection_id="dc1", body='{"password": "rotated"}'),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        capture = {}
        mock_client = create_mock_client(200, {"id": "dc1"}, capture=capture)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "edit_data_connection"
        assert capture["json"]["password"] == "rotated"


class TestHexSemanticModelsMock:
    @pytest.mark.asyncio
    async def test_ingest_semantic_project(self, api_credentials):
        config = HexNodeConfig(
            config=HexIngestSemanticProjectConfig(semantic_project_id="sp1", body='{"source": "zip"}'),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "ingest_semantic_project"


class TestHexWorkspaceHostMock:
    @pytest.mark.asyncio
    async def test_custom_workspace_host_in_url(self):
        """Single-tenant/EU host is honored in the request URL."""
        creds = HexApiTokenCredential(api_token="hxtw_x", workspace_host="eu.hex.tech")
        config = HexNodeConfig(config=HexGetMeConfig(), credentials=creds)
        node = create_hex_node(config)
        capture = {}
        mock_client = create_mock_client(200, {"id": "u1"}, capture=capture)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert capture["url"] == "https://eu.hex.tech/api/v1/users/me"


class TestHexErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_credentials):
        config = HexNodeConfig(
            config=HexGetProjectConfig(project_id="missing"), credentials=api_credentials
        )
        node = create_hex_node(config)
        mock_client = create_mock_client(404, {"reason": "Project not found"})
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_invalid_json_body_raises(self, api_credentials):
        config = HexNodeConfig(
            config=HexUpdateProjectConfig(project_id="p1", body="{not valid json"),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        with pytest.raises(ValueError, match="must be valid JSON"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = HexNodeConfig(config=HexGetMeConfig(), credentials=None)
        node = create_hex_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestHexDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_project_options(self):
        with patch(
            "utils.credential_loader.load_credential",
            return_value={"api_token": "hxtp_x", "workspace_host": "app.hex.tech"},
        ), patch(
            "nodes.hex_node._hex_request",
            return_value={
                "status": "success",
                "data": {"values": [{"id": "p1", "title": "Sales"}, {"id": "p2", "title": "Ops"}]},
            },
        ):
            result = await HexNode.load_field_options(
                "project_id", "user-1", {}, credential_ids={"hex": "cred-1"}, pool=Mock()
            )
        assert "options" in result
        assert result["options"][0]["value"] == "p1"
        assert result["options"][0]["label"] == "Sales"

    @pytest.mark.asyncio
    async def test_load_options_unknown_field(self):
        result = await HexNode.load_field_options(
            "unknown_field", "user-1", {}, credential_ids={"hex": "cred-1"}, pool=Mock()
        )
        assert result == {"options": []}


class TestHexTriggerMock:
    def test_resolve_trigger_payload_poll_returns_none(self):
        """Poll-based trigger returns None so execute() runs and actually polls."""
        payload = {"some": "webhook wake-up signal"}
        result = HexNode.resolve_trigger_payload(
            payload, {"operation": "on_run_completed"}
        )
        assert result is None

    def test_resolve_trigger_payload_always_returns_none(self):
        """Mixin resolve_trigger_payload always returns None (wake-up-and-poll for any op)."""
        payload = {"some": "data"}
        result = HexNode.resolve_trigger_payload(
            payload, {"operation": "get_run_status"}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_on_run_completed_first_poll_baselines(self, api_credentials):
        """First poll: records current terminal runs as seen, emits nothing (baseline)."""
        config = HexNodeConfig(
            config=HexOnRunCompletedConfig(project_id="proj-1"),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        runs = {
            "runs": [
                {"runId": "run-3", "status": "COMPLETED"},
                {"runId": "run-2", "status": "ERRORED"},
                {"runId": "run-1", "status": "RUNNING"},  # not terminal, excluded
            ]
        }
        mock_client = create_mock_client(200, runs)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client), \
             patch.object(node, "_load_node_state", return_value={}), \
             patch.object(node, "_save_node_state") as mock_save:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["operation"] == "on_run_completed"
        # First poll always emits nothing (baseline)
        assert result["new_count"] == 0
        assert result["items"] == []
        # Seen IDs were persisted (run-3 and run-2 — the terminal ones)
        saved = mock_save.call_args[0][0]
        assert set(saved["seen_ids"]) == {"run-3", "run-2"}

    @pytest.mark.asyncio
    async def test_on_run_completed_emits_unseen_terminal_runs(self, api_credentials):
        """Subsequent poll: only runs not in seen_ids are emitted."""
        config = HexNodeConfig(
            config=HexOnRunCompletedConfig(project_id="proj-1"),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        runs = {
            "runs": [
                {"runId": "run-4", "status": "COMPLETED"},
                {"runId": "run-3", "status": "KILLED"},
                {"runId": "run-2", "status": "COMPLETED"},  # already seen
                {"runId": "run-1", "status": "COMPLETED"},  # already seen
            ]
        }
        mock_client = create_mock_client(200, runs)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client), \
             patch.object(node, "_load_node_state", return_value={"seen_ids": ["run-2", "run-1"]}), \
             patch.object(node, "_save_node_state"):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["new_count"] == 2
        assert [r["runId"] for r in result["items"]] == ["run-4", "run-3"]

    @pytest.mark.asyncio
    async def test_on_run_completed_no_new_runs(self, api_credentials):
        """When all terminal runs were already seen, emit zero items."""
        config = HexNodeConfig(
            config=HexOnRunCompletedConfig(project_id="proj-1"),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        runs = {
            "runs": [
                {"runId": "run-3", "status": "COMPLETED"},
                {"runId": "run-2", "status": "COMPLETED"},
            ]
        }
        mock_client = create_mock_client(200, runs)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client), \
             patch.object(node, "_load_node_state", return_value={"seen_ids": ["run-3", "run-2"]}), \
             patch.object(node, "_save_node_state"):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["new_count"] == 0
        assert result["items"] == []
        # trigger_produced_no_event must suppress downstream
        assert node.trigger_produced_no_event(result) is True

    @pytest.mark.asyncio
    async def test_on_run_completed_status_filter(self, api_credentials):
        """status_filter restricts which terminal statuses are considered."""
        config = HexNodeConfig(
            config=HexOnRunCompletedConfig(project_id="proj-1", status_filter="ERRORED"),
            credentials=api_credentials,
        )
        node = create_hex_node(config)
        runs = {
            "runs": [
                {"runId": "run-3", "status": "COMPLETED"},  # filtered out (not ERRORED)
                {"runId": "run-2", "status": "ERRORED"},
            ]
        }
        mock_client = create_mock_client(200, runs)
        with patch("nodes.hex_node.httpx.AsyncClient", return_value=mock_client), \
             patch.object(node, "_load_node_state", return_value={"seen_ids": []}), \
             patch.object(node, "_save_node_state"):
            result = await node.execute({})
        assert result["new_count"] == 1
        assert result["items"][0]["runId"] == "run-2"
