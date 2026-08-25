"""
Mock tests for the OneLake (Microsoft Fabric) node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Filesystem: list paths, create directory/file, append, flush, read, get
  properties, get/check access, lease, set properties, rename, delete, list blobs
- Tables: Iceberg config / namespaces / namespace / tables / table, Delta
  schemas / tables / table
- Shortcuts & settings: create / bulk create / get / list / delete shortcut,
  reset cache, get settings
- Data access security (RBAC): list / get / create-or-update / delete role
- Audience routing: DFS/Table ops carry the Storage token, Fabric Core ops carry
  the Fabric token (a single token can't span both `aud` claims)
- Trigger: poll-based on_new_file with node-state seen-set dedup (mixin)
- Error handling, missing credentials, workspace dropdown

The two-audience token minting is mocked (``_ensure_tokens`` → fixed Storage /
Fabric tokens) so tests hit only the request layer and can assert which token
rode each request.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock

from nodes.onelake_node import (
    OneLakeNode,
    OneLakeNodeConfig,
    OneLakeOAuthCredential,
    STORAGE_SCOPE,
    FABRIC_SCOPE,
    FABRIC_AUDIENCE_OPS,
    OneLakeListPathsConfig,
    OneLakeCreateDirectoryConfig,
    OneLakeCreateFileConfig,
    OneLakeAppendFileConfig,
    OneLakeFlushFileConfig,
    OneLakeReadFileConfig,
    OneLakeGetPropertiesConfig,
    OneLakeGetAccessControlConfig,
    OneLakeCheckAccessConfig,
    OneLakeLeasePathConfig,
    OneLakeSetPropertiesConfig,
    OneLakeRenamePathConfig,
    OneLakeDeletePathConfig,
    OneLakeListBlobsConfig,
    OneLakeOnNewFileConfig,
    OneLakeGetIcebergConfigConfig,
    OneLakeListIcebergNamespacesConfig,
    OneLakeGetIcebergNamespaceConfig,
    OneLakeListIcebergTablesConfig,
    OneLakeGetIcebergTableConfig,
    OneLakeListDeltaSchemasConfig,
    OneLakeListDeltaTablesConfig,
    OneLakeGetDeltaTableConfig,
    OneLakeCreateShortcutConfig,
    OneLakeCreateShortcutsBulkConfig,
    OneLakeGetShortcutConfig,
    OneLakeListShortcutsConfig,
    OneLakeDeleteShortcutConfig,
    OneLakeResetShortcutCacheConfig,
    OneLakeGetSettingsConfig,
    OneLakeListDataAccessRolesConfig,
    OneLakeGetDataAccessRoleConfig,
    OneLakeCreateOrUpdateDataAccessRoleConfig,
    OneLakeDeleteDataAccessRoleConfig,
)

# The two per-audience tokens the node mints at execute time. Tests assert which
# one each operation's request carries (Storage for DFS/Table, Fabric for Core).
STORAGE_TOKEN = "storage-audience-token"
FABRIC_TOKEN = "fabric-audience-token"


@pytest.fixture(autouse=True)
def mock_tokens():
    """Short-circuit the two-audience token minting so execute() proceeds to the
    mocked HTTP layer without hitting the real Microsoft token endpoint."""
    with patch.object(
        OneLakeNode,
        "_ensure_tokens",
        new=AsyncMock(return_value=(STORAGE_TOKEN, FABRIC_TOKEN)),
    ):
        yield


@pytest.fixture
def oauth_credentials():
    return OneLakeOAuthCredential(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at="2099-12-31T23:59:59Z",
        email="test@example.com",
    )


def create_onelake_node(config):
    return OneLakeNode(
        node_id="test-onelake-node",
        node_type="automation-onelake",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, headers=None, content=b"x"):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.content = content
    mock_response.headers = headers if headers is not None else {"content-type": "application/json"}
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, headers=None, content=b"x"):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager. Captures each request's kwargs on
    ``mock_client.calls`` so tests can assert the URL, method, and (crucially)
    which audience token rode in the Authorization header."""
    mock_response = create_mock_response(status_code, json_data, headers, content)
    mock_client = Mock()
    mock_client.calls = []

    async def async_request(*args, **kwargs):
        mock_client.calls.append(kwargs)
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


def _auth_token(mock_client):
    """The bearer token from the last captured request's Authorization header."""
    hdr = mock_client.calls[-1]["headers"]["Authorization"]
    return hdr.replace("Bearer ", "")


# ============================================================================
# Filesystem operations
# ============================================================================


class TestOneLakeFilesystemMock:
    @pytest.mark.asyncio
    async def test_list_paths(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListPathsConfig(workspace="MyWorkspace", directory="MyLake.lakehouse/Files"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"paths": [{"name": "a.csv"}, {"name": "b.csv"}]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_paths"
        assert len(result["data"]["paths"]) == 2

    @pytest.mark.asyncio
    async def test_create_directory(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeCreateDirectoryConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", path="reports/2026"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(201, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_directory"

    @pytest.mark.asyncio
    async def test_create_file(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeCreateFileConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", path="data/input.csv"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(201, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_file"

    @pytest.mark.asyncio
    async def test_append_file(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeAppendFileConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", path="data/input.csv",
                content="hello,world", position="0",
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(202, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "append_file"

    @pytest.mark.asyncio
    async def test_flush_file(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeFlushFileConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", path="data/input.csv", length="11"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "flush_file"

    @pytest.mark.asyncio
    async def test_read_file(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeReadFileConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", path="data/input.csv"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(
            200, None, headers={"content-type": "application/octet-stream"}, content=b"hello,world"
        )
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "read_file"
        assert "raw" in result["data"]

    @pytest.mark.asyncio
    async def test_get_properties(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeGetPropertiesConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", path="data/input.csv"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(
            200, None, headers={"content-type": "application/octet-stream", "content-length": "11", "etag": "abc"}, content=b""
        )
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_properties"
        assert result["data"]["headers"]["etag"] == "abc"

    @pytest.mark.asyncio
    async def test_get_access_control(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeGetAccessControlConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", path="data/input.csv"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(
            200, None, headers={"content-type": "application/octet-stream", "x-ms-acl": "user::rwx"}, content=b""
        )
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_access_control"
        assert result["data"]["headers"]["x-ms-acl"] == "user::rwx"

    @pytest.mark.asyncio
    async def test_set_properties(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeSetPropertiesConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", path="data/input.csv",
                properties="key1=dmFsdWU=",
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "set_properties"

    @pytest.mark.asyncio
    async def test_rename_path(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeRenamePathConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse",
                source_path="data/old.csv", destination_path="data/new.csv",
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(201, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "rename_path"

    @pytest.mark.asyncio
    async def test_delete_path(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeDeletePathConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", path="data/old.csv", recursive="true"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_path"


# ============================================================================
# Table API operations
# ============================================================================


class TestOneLakeTablesMock:
    @pytest.mark.asyncio
    async def test_get_iceberg_config(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeGetIcebergConfigConfig(workspace="MyWorkspace", item="MyLake.lakehouse"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"defaults": {}, "overrides": {"prefix": "abc123"}})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_iceberg_config"
        assert result["data"]["overrides"]["prefix"] == "abc123"

    @pytest.mark.asyncio
    async def test_list_iceberg_namespaces(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListIcebergNamespacesConfig(prefix="abc123"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"namespaces": [["dbo"]]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_iceberg_namespaces"

    @pytest.mark.asyncio
    async def test_list_iceberg_tables(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListIcebergTablesConfig(prefix="abc123", schema_name="dbo"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"identifiers": [{"name": "sales"}]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_iceberg_tables"

    @pytest.mark.asyncio
    async def test_get_iceberg_table(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeGetIcebergTableConfig(prefix="abc123", schema_name="dbo", table="sales"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"metadata": {"table-uuid": "uuid-1"}})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_iceberg_table"

    @pytest.mark.asyncio
    async def test_list_delta_schemas(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListDeltaSchemasConfig(workspace="MyWorkspace", item="MyLake.lakehouse"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"schemas": [{"name": "dbo"}]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_delta_schemas"

    @pytest.mark.asyncio
    async def test_list_delta_tables(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListDeltaTablesConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", schema_name="dbo"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"tables": [{"name": "sales"}]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_delta_tables"

    @pytest.mark.asyncio
    async def test_get_delta_table(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeGetDeltaTableConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", full_name="MyLake.dbo.sales"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"name": "sales", "table_type": "MANAGED"})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_delta_table"
        assert result["data"]["name"] == "sales"


# ============================================================================
# Shortcut & settings operations
# ============================================================================


class TestOneLakeShortcutsMock:
    @pytest.mark.asyncio
    async def test_create_shortcut(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeCreateShortcutConfig(
                workspace_id="ws-guid", item_id="item-guid", name="myShortcut", path="Tables",
                target='{"oneLake": {"workspaceId": "ws2", "itemId": "item2", "path": "Tables/sales"}}',
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(201, {"name": "myShortcut", "path": "Tables"})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_shortcut"
        assert result["data"]["name"] == "myShortcut"

    @pytest.mark.asyncio
    async def test_create_shortcut_invalid_target(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeCreateShortcutConfig(
                workspace_id="ws-guid", item_id="item-guid", name="myShortcut", path="Tables",
                target="not-json",
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        # No HTTP call should happen — JSON parse fails first.
        result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 400
        assert "valid JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_get_shortcut(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeGetShortcutConfig(
                workspace_id="ws-guid", item_id="item-guid", shortcut_path="Tables", shortcut_name="myShortcut"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"name": "myShortcut", "target": {}})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_shortcut"

    @pytest.mark.asyncio
    async def test_list_shortcuts(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListShortcutsConfig(workspace_id="ws-guid", item_id="item-guid"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"value": [{"name": "myShortcut"}]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_shortcuts"
        assert len(result["data"]["value"]) == 1

    @pytest.mark.asyncio
    async def test_delete_shortcut(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeDeleteShortcutConfig(
                workspace_id="ws-guid", item_id="item-guid", shortcut_path="Tables", shortcut_name="myShortcut"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_shortcut"

    @pytest.mark.asyncio
    async def test_reset_shortcut_cache(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeResetShortcutCacheConfig(workspace_id="ws-guid"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "reset_shortcut_cache"

    @pytest.mark.asyncio
    async def test_get_settings(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeGetSettingsConfig(workspace_id="ws-guid"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"oneLakeRegion": "westus"})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_settings"
        assert result["data"]["oneLakeRegion"] == "westus"


# ============================================================================
# Error handling
# ============================================================================


class TestOneLakeErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeGetSettingsConfig(workspace_id="missing"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(404, {"error": {"message": "Workspace not found", "code": "NotFound"}})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = OneLakeNodeConfig(config=OneLakeGetSettingsConfig(workspace_id="ws"), credentials=None)
        node = create_onelake_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestOneLakeDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_workspace_options(self):
        """The workspace dropdown mints a Fabric-audience token from the
        pre-loaded credential's refresh token and lists workspaces via Core."""
        fake_fabric = Mock(access_token="fabric-tok")
        with patch(
            "nodes.oauth.microsoft_oauth.refresh_access_token",
            new=AsyncMock(return_value=fake_fabric),
        ) as mock_refresh, patch(
            "nodes.onelake_node._onelake_request",
            new=AsyncMock(return_value={
                "status": "success",
                "data": {"value": [{"id": "ws-1", "displayName": "Analytics"}]},
            }),
        ) as mock_req:
            result = await OneLakeNode.load_field_options(
                "workspace", {"refresh_token": "rt", "access_token": "at"}
            )
        assert result["options"][0]["value"] == "Analytics"
        assert result["options"][0]["label"] == "Analytics"
        # Minted with the Fabric audience, and the request carried that token.
        mock_refresh.assert_awaited_once()
        assert mock_refresh.await_args.kwargs.get("scope") == FABRIC_SCOPE
        assert mock_req.await_args.args[0] == "fabric-tok"

    @pytest.mark.asyncio
    async def test_load_workspace_options_no_refresh_token(self):
        result = await OneLakeNode.load_field_options("workspace", {"access_token": "at"})
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_load_options_unknown_field(self):
        result = await OneLakeNode.load_field_options("nope", {"refresh_token": "rt"})
        assert result == {"options": []}


# ============================================================================
# New operations, audience routing, and the poll-based trigger
# ============================================================================


def call_url(mock_client):
    """The URL of the last captured request."""
    return mock_client.calls[-1]["url"]


class TestOneLakeNewOperationsMock:
    @pytest.mark.asyncio
    async def test_check_access(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeCheckAccessConfig(
                workspace="MyWorkspace", item="MyLake.lakehouse", path="Files/x.csv", fs_action="rwx"
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        call = mock_client.calls[-1]
        assert call["method"] == "HEAD"
        assert call["params"]["action"] == "checkAccess"
        assert call["params"]["fsAction"] == "rwx"
        assert _auth_token(mock_client) == STORAGE_TOKEN

    @pytest.mark.asyncio
    async def test_lease_path_acquire(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeLeasePathConfig(
                workspace="W", item="I.lakehouse", path="Files/x.csv",
                lease_action="acquire", proposed_lease_id="lease-guid", duration=30,
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(201, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        call = mock_client.calls[-1]
        assert call["params"]["comp"] == "lease"
        assert call["headers"]["x-ms-lease-action"] == "acquire"
        assert call["headers"]["x-ms-proposed-lease-id"] == "lease-guid"
        assert call["headers"]["x-ms-lease-duration"] == "30"

    @pytest.mark.asyncio
    async def test_list_blobs(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListBlobsConfig(workspace="W", prefix="MyLake.lakehouse/Files/"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, None, headers={"content-type": "application/xml"}, content=b"<xml/>")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        call = mock_client.calls[-1]
        assert "onelake.blob.fabric.microsoft.com" in call["url"]
        assert call["params"]["restype"] == "container"
        assert call["params"]["comp"] == "list"
        assert _auth_token(mock_client) == STORAGE_TOKEN

    @pytest.mark.asyncio
    async def test_get_iceberg_namespace(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeGetIcebergNamespaceConfig(prefix="pfx", schema_name="dbo"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"namespace": ["dbo"], "properties": {}})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert call_url(mock_client).endswith("/iceberg/v1/pfx/namespaces/dbo")
        assert _auth_token(mock_client) == STORAGE_TOKEN

    @pytest.mark.asyncio
    async def test_create_shortcuts_bulk(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeCreateShortcutsBulkConfig(
                workspace_id="ws", item_id="it",
                shortcuts='[{"name":"s1","path":"Tables","target":{"oneLake":{}}}]',
                conflict_policy="Abort",
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"value": []})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        call = mock_client.calls[-1]
        assert call["url"].endswith("/items/it/shortcuts/bulkCreate")
        assert call["json"]["createShortcutRequests"][0]["name"] == "s1"
        assert _auth_token(mock_client) == FABRIC_TOKEN

    @pytest.mark.asyncio
    async def test_create_shortcuts_bulk_invalid_json(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeCreateShortcutsBulkConfig(
                workspace_id="ws", item_id="it", shortcuts="not-json",
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 400

    @pytest.mark.asyncio
    async def test_list_data_access_roles(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListDataAccessRolesConfig(workspace_id="ws", item_id="it"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"value": [{"name": "readers"}]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert call_url(mock_client).endswith("/items/it/dataAccessRoles")
        assert _auth_token(mock_client) == FABRIC_TOKEN

    @pytest.mark.asyncio
    async def test_get_data_access_role(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeGetDataAccessRoleConfig(workspace_id="ws", item_id="it", role_name="readers"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"name": "readers"})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert call_url(mock_client).endswith("/dataAccessRoles/readers")

    @pytest.mark.asyncio
    async def test_create_or_update_data_access_role(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeCreateOrUpdateDataAccessRoleConfig(
                workspace_id="ws", item_id="it", role_name="readers",
                definition='{"decisionRules":[]}', etag="etag-1",
            ),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"name": "readers"})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        call = mock_client.calls[-1]
        assert call["method"] == "PUT"
        assert call["headers"]["If-Match"] == "etag-1"
        assert call["json"] == {"decisionRules": []}
        assert _auth_token(mock_client) == FABRIC_TOKEN

    @pytest.mark.asyncio
    async def test_delete_data_access_role(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeDeleteDataAccessRoleConfig(workspace_id="ws", item_id="it", role_name="readers"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, None, headers={"content-type": "text/plain"}, content=b"")
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        call = mock_client.calls[-1]
        assert call["method"] == "DELETE"


class TestOneLakeAudienceRoutingMock:
    """The single most important auth invariant: DFS/Table ops carry the Storage
    token; Fabric Core ops carry the Fabric token. A single token can't span both
    `aud` claims, so mis-routing = guaranteed 401."""

    @pytest.mark.asyncio
    async def test_dfs_op_uses_storage_token(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListPathsConfig(workspace="W"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"paths": []})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            await node.execute({})
        assert _auth_token(mock_client) == STORAGE_TOKEN

    @pytest.mark.asyncio
    async def test_table_op_uses_storage_token(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListDeltaSchemasConfig(workspace="W", item="L.Lakehouse"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"schemas": []})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            await node.execute({})
        assert _auth_token(mock_client) == STORAGE_TOKEN

    @pytest.mark.asyncio
    async def test_core_op_uses_fabric_token(self, oauth_credentials):
        config = OneLakeNodeConfig(
            config=OneLakeListShortcutsConfig(workspace_id="ws", item_id="it"),
            credentials=oauth_credentials,
        )
        node = create_onelake_node(config)
        mock_client = create_mock_client(200, {"value": []})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            await node.execute({})
        assert _auth_token(mock_client) == FABRIC_TOKEN

    def test_fabric_audience_ops_set_matches_core_handlers(self):
        # Every op in FABRIC_AUDIENCE_OPS must be a real registered operation.
        import json
        schema = OneLakeNode.get_config_schema()
        cfg = schema["properties"]["config"]
        defs = schema.get("$defs", {})
        ops = set()
        for entry in (cfg.get("anyOf") or cfg.get("oneOf") or []):
            name = entry.get("$ref", "").split("/")[-1]
            props = defs.get(name, {}).get("properties", {})
            op = props.get("operation", {}).get("const") or props.get("operation", {}).get("default")
            if op:
                ops.add(op)
        assert FABRIC_AUDIENCE_OPS.issubset(ops)


class TestOneLakeTriggerMock:
    def test_resolve_trigger_payload_is_wakeup_signal(self):
        """The mixin treats the cron POST as a wake-up: execute() runs the poll."""
        assert OneLakeNode.resolve_trigger_payload({"x": 1}, {"operation": "on_new_file"}) is None

    def _poll_node(self, oauth_credentials, state_store):
        cfg = OneLakeOnNewFileConfig(workspace="W", directory="L.lakehouse/Files")
        node = create_onelake_node(OneLakeNodeConfig(config=cfg, credentials=oauth_credentials))

        async def _load():
            return dict(state_store)

        async def _save(state, **_):
            state_store.clear()
            state_store.update(state)

        node._load_node_state = _load
        node._save_node_state = _save
        return node

    @pytest.mark.asyncio
    async def test_poll_first_run_baselines_silently(self, oauth_credentials):
        state = {}
        node = self._poll_node(oauth_credentials, state)
        mock_client = create_mock_client(200, {"paths": [
            {"name": "Files/a.csv", "isDirectory": "false"},
            {"name": "Files/b.csv", "isDirectory": "false"},
        ]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["new_count"] == 0
        assert set(state["seen_ids"]) == {"Files/a.csv", "Files/b.csv"}
        assert node.trigger_produced_no_event(result) is True

    @pytest.mark.asyncio
    async def test_poll_emits_only_new_files(self, oauth_credentials):
        state = {"seen_ids": ["Files/a.csv"]}
        node = self._poll_node(oauth_credentials, state)
        mock_client = create_mock_client(200, {"paths": [
            {"name": "Files/a.csv", "isDirectory": "false"},
            {"name": "Files/b.csv", "isDirectory": "false"},
            {"name": "Files/c.csv", "isDirectory": "false"},
        ]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["new_count"] == 2
        assert {i["name"] for i in result["items"]} == {"Files/b.csv", "Files/c.csv"}
        assert node.trigger_produced_no_event(result) is False

    @pytest.mark.asyncio
    async def test_poll_dedupes_already_seen(self, oauth_credentials):
        state = {"seen_ids": ["Files/a.csv", "Files/b.csv"]}
        node = self._poll_node(oauth_credentials, state)
        mock_client = create_mock_client(200, {"paths": [
            {"name": "Files/a.csv", "isDirectory": "false"},
            {"name": "Files/b.csv", "isDirectory": "false"},
        ]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["new_count"] == 0
        assert node.trigger_produced_no_event(result) is True

    @pytest.mark.asyncio
    async def test_poll_ignores_directories(self, oauth_credentials):
        state = {"seen_ids": []}
        node = self._poll_node(oauth_credentials, state)
        mock_client = create_mock_client(200, {"paths": [
            {"name": "Files/subdir", "isDirectory": "true"},
            {"name": "Files/new.csv", "isDirectory": "false"},
        ]})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["new_count"] == 1
        assert result["items"][0]["name"] == "Files/new.csv"

    @pytest.mark.asyncio
    async def test_poll_uses_storage_token(self, oauth_credentials):
        node = self._poll_node(oauth_credentials, {"seen_ids": []})
        mock_client = create_mock_client(200, {"paths": []})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            await node.execute({})
        assert _auth_token(mock_client) == STORAGE_TOKEN

    @pytest.mark.asyncio
    async def test_poll_api_error_propagates(self, oauth_credentials):
        node = self._poll_node(oauth_credentials, {"seen_ids": []})
        mock_client = create_mock_client(404, {"error": {"message": "Filesystem not found"}})
        with patch("nodes.onelake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
