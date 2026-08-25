"""
Mock tests for the Sigma Computing REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Workbooks: list, get, create, update, delete, export, download, materialize, sources
- Members: list, get, create, update, delete
- Teams: list, create, add members, remove member
- Connections: list, create, test
- Workspaces: list, create, add grant
- Catalog: list files, list data models, get data model spec, list account types, list api credentials
- Error handling: API errors, token failure, missing credentials
- Dynamic options: workbook dropdown

The token exchange (`_sigma_get_token`) is patched so every test runs against
a single mocked Bearer token.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from nodes.sigma_node import (
    SigmaNode,
    SigmaNodeConfig,
    SigmaApiKeyCredential,
    SigmaListWorkbooksConfig,
    SigmaGetWorkbookConfig,
    SigmaCreateWorkbookConfig,
    SigmaUpdateWorkbookConfig,
    SigmaDeleteWorkbookConfig,
    SigmaExportWorkbookConfig,
    SigmaDownloadExportConfig,
    SigmaMaterializeWorkbookConfig,
    SigmaGetWorkbookSourcesConfig,
    SigmaListMembersConfig,
    SigmaGetMemberConfig,
    SigmaCreateMemberConfig,
    SigmaUpdateMemberConfig,
    SigmaDeleteMemberConfig,
    SigmaListTeamsConfig,
    SigmaCreateTeamConfig,
    SigmaAddTeamMembersConfig,
    SigmaRemoveTeamMemberConfig,
    SigmaListConnectionsConfig,
    SigmaCreateConnectionConfig,
    SigmaTestConnectionConfig,
    SigmaListWorkspacesConfig,
    SigmaCreateWorkspaceConfig,
    SigmaAddWorkspaceGrantConfig,
    SigmaListFilesConfig,
    SigmaListDataModelsConfig,
    SigmaGetDataModelSpecConfig,
    SigmaListAccountTypesConfig,
    SigmaListApiCredentialsConfig,
    SigmaOnExportCompletedConfig,
    _TOKEN_CACHE,
    _sigma_get_token,
    _sigma_token_cache_key,
)


@pytest.fixture
def credentials():
    return SigmaApiKeyCredential(
        client_id="sigma_client_123",
        client_secret="sigma_secret_456",
        region="aws-us-west",
    )


@pytest.fixture(autouse=True)
def clear_token_cache():
    _TOKEN_CACHE.clear()
    yield
    _TOKEN_CACHE.clear()


def create_sigma_node(config):
    return SigmaNode(
        node_id="test-sigma-node",
        node_type="automation-sigma",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


async def _run(node, status_code=200, json_data=None):
    """Patch the token exchange + the HTTP client, then run the node."""
    mock_client = create_mock_client(status_code, json_data)
    with patch(
        "nodes.sigma_node._sigma_get_token", return_value="mock_token"
    ), patch("nodes.sigma_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Token cache
# ============================================================================


@pytest.mark.asyncio
async def test_sigma_token_reuses_exact_credentials_without_raw_secret_key():
    base_url = "https://aws-api.sigmacomputing.com/v2"
    response = MagicMock(status_code=200)
    response.json.return_value = {"access_token": "sigma-token", "expires_in": 3600}

    with patch("nodes.sigma_node.httpx.AsyncClient") as client_cls, patch(
        "nodes.sigma_node.time.monotonic", return_value=1000.0
    ):
        client = AsyncMock()
        client.post.return_value = response
        client_cls.return_value.__aenter__.return_value = client

        first = await _sigma_get_token(base_url, "client-id", "client-secret")
        second = await _sigma_get_token(base_url, "client-id", "client-secret")

    assert first == second == "sigma-token"
    client.post.assert_awaited_once()
    cache_key = _sigma_token_cache_key(base_url, "client-id", "client-secret")
    assert len(cache_key) == 64
    assert "client-secret" not in cache_key


@pytest.mark.asyncio
async def test_sigma_same_public_fields_with_different_secret_do_not_share_token():
    base_url = "https://aws-api.sigmacomputing.com/v2"
    first_response = MagicMock(status_code=200)
    first_response.json.return_value = {
        "access_token": "first-secret-token",
        "expires_in": 3600,
    }
    second_response = MagicMock(status_code=200)
    second_response.json.return_value = {
        "access_token": "second-secret-token",
        "expires_in": 3600,
    }

    with patch("nodes.sigma_node.httpx.AsyncClient") as client_cls, patch(
        "nodes.sigma_node.time.monotonic", return_value=1000.0
    ):
        client = AsyncMock()
        client.post.side_effect = [first_response, second_response]
        client_cls.return_value.__aenter__.return_value = client

        first = await _sigma_get_token(base_url, "same-client", "first-secret")
        second = await _sigma_get_token(base_url, "same-client", "second-secret")

    assert first == "first-secret-token"
    assert second == "second-secret-token"
    assert client.post.await_count == 2


@pytest.mark.asyncio
async def test_sigma_expired_token_is_refreshed():
    base_url = "https://aws-api.sigmacomputing.com/v2"
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

    with patch("nodes.sigma_node.httpx.AsyncClient") as client_cls, patch(
        "nodes.sigma_node.time.monotonic", side_effect=lambda: now[0]
    ):
        client = AsyncMock()
        client.post.side_effect = [first_response, second_response]
        client_cls.return_value.__aenter__.return_value = client

        assert await _sigma_get_token(base_url, "client-id", "secret") == "short-token"
        now[0] = 1060.0
        assert await _sigma_get_token(base_url, "client-id", "secret") == "refreshed-token"

    assert client.post.await_count == 2


# ============================================================================
# Workbooks
# ============================================================================


class TestSigmaWorkbooksMock:
    @pytest.mark.asyncio
    async def test_list_workbooks(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListWorkbooksConfig(limit="10"), credentials=credentials)
        )
        result = await _run(node, 200, {"entries": [{"workbookId": "wb_1"}], "hasMore": False})
        assert result["status"] == "success"
        assert result["action"] == "list_workbooks"
        assert result["data"]["entries"][0]["workbookId"] == "wb_1"

    @pytest.mark.asyncio
    async def test_get_workbook(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaGetWorkbookConfig(workbook_id="wb_1"), credentials=credentials)
        )
        result = await _run(node, 200, {"workbookId": "wb_1", "name": "Sales"})
        assert result["status"] == "success"
        assert result["action"] == "get_workbook"
        assert result["data"]["name"] == "Sales"

    @pytest.mark.asyncio
    async def test_create_workbook(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaCreateWorkbookConfig(name="New WB"), credentials=credentials)
        )
        result = await _run(node, 201, {"workbookId": "wb_new"})
        assert result["status"] == "success"
        assert result["action"] == "create_workbook"
        assert result["data"]["workbookId"] == "wb_new"

    @pytest.mark.asyncio
    async def test_update_workbook(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaUpdateWorkbookConfig(workbook_id="wb_1", name="Renamed"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"workbookId": "wb_1", "name": "Renamed"})
        assert result["status"] == "success"
        assert result["action"] == "update_workbook"

    @pytest.mark.asyncio
    async def test_delete_workbook(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaDeleteWorkbookConfig(workbook_id="wb_1"), credentials=credentials)
        )
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_workbook"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_export_workbook(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaExportWorkbookConfig(workbook_id="wb_1", export_format="csv"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"queryId": "q_123"})
        assert result["status"] == "success"
        assert result["action"] == "export_workbook"
        assert result["data"]["queryId"] == "q_123"

    @pytest.mark.asyncio
    async def test_download_export(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaDownloadExportConfig(query_id="q_123"), credentials=credentials)
        )
        result = await _run(node, 200, {"url": "https://download/q_123"})
        assert result["status"] == "success"
        assert result["action"] == "download_export"

    @pytest.mark.asyncio
    async def test_materialize_workbook(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaMaterializeWorkbookConfig(workbook_id="wb_1"), credentials=credentials
            )
        )
        result = await _run(node, 200, {"materializationId": "m_1"})
        assert result["status"] == "success"
        assert result["action"] == "materialize_workbook"

    @pytest.mark.asyncio
    async def test_get_workbook_sources(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaGetWorkbookSourcesConfig(workbook_id="wb_1"), credentials=credentials
            )
        )
        result = await _run(node, 200, {"entries": [{"connectionId": "c_1"}]})
        assert result["status"] == "success"
        assert result["action"] == "get_workbook_sources"


# ============================================================================
# Members
# ============================================================================


class TestSigmaMembersMock:
    @pytest.mark.asyncio
    async def test_list_members(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListMembersConfig(limit="10"), credentials=credentials)
        )
        result = await _run(node, 200, {"entries": [{"memberId": "u_1"}], "hasMore": False})
        assert result["status"] == "success"
        assert result["action"] == "list_members"

    @pytest.mark.asyncio
    async def test_get_member(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaGetMemberConfig(member_id="u_1"), credentials=credentials)
        )
        result = await _run(node, 200, {"memberId": "u_1", "email": "a@b.com"})
        assert result["status"] == "success"
        assert result["action"] == "get_member"
        assert result["data"]["email"] == "a@b.com"

    @pytest.mark.asyncio
    async def test_create_member(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaCreateMemberConfig(
                    email="new@b.com", first_name="New", last_name="Person"
                ),
                credentials=credentials,
            )
        )
        result = await _run(node, 201, {"memberId": "u_new"})
        assert result["status"] == "success"
        assert result["action"] == "create_member"
        assert result["data"]["memberId"] == "u_new"

    @pytest.mark.asyncio
    async def test_update_member(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaUpdateMemberConfig(member_id="u_1", first_name="Updated"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"memberId": "u_1", "firstName": "Updated"})
        assert result["status"] == "success"
        assert result["action"] == "update_member"

    @pytest.mark.asyncio
    async def test_delete_member(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaDeleteMemberConfig(member_id="u_1"), credentials=credentials)
        )
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_member"


# ============================================================================
# Teams
# ============================================================================


class TestSigmaTeamsMock:
    @pytest.mark.asyncio
    async def test_list_teams(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListTeamsConfig(), credentials=credentials)
        )
        result = await _run(node, 200, {"entries": [{"teamId": "t_1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_teams"

    @pytest.mark.asyncio
    async def test_create_team(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaCreateTeamConfig(name="Eng"), credentials=credentials)
        )
        result = await _run(node, 201, {"teamId": "t_new"})
        assert result["status"] == "success"
        assert result["action"] == "create_team"
        assert result["data"]["teamId"] == "t_new"

    @pytest.mark.asyncio
    async def test_add_team_members(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaAddTeamMembersConfig(team_id="t_1", member_ids="u_1,u_2"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"added": 2})
        assert result["status"] == "success"
        assert result["action"] == "add_team_members"

    @pytest.mark.asyncio
    async def test_remove_team_member(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaRemoveTeamMemberConfig(team_id="t_1", member_id="u_1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "remove_team_member"


# ============================================================================
# Connections
# ============================================================================


class TestSigmaConnectionsMock:
    @pytest.mark.asyncio
    async def test_list_connections(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListConnectionsConfig(), credentials=credentials)
        )
        result = await _run(node, 200, {"entries": [{"connectionId": "c_1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_connections"

    @pytest.mark.asyncio
    async def test_create_connection(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaCreateConnectionConfig(name="Snowflake", connection_type="snowflake"),
                credentials=credentials,
            )
        )
        result = await _run(node, 201, {"connectionId": "c_new"})
        assert result["status"] == "success"
        assert result["action"] == "create_connection"
        assert result["data"]["connectionId"] == "c_new"

    @pytest.mark.asyncio
    async def test_test_connection(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaTestConnectionConfig(connection_id="c_1"), credentials=credentials
            )
        )
        result = await _run(node, 200, {"read": True, "write": True})
        assert result["status"] == "success"
        assert result["action"] == "test_connection"


# ============================================================================
# Workspaces
# ============================================================================


class TestSigmaWorkspacesMock:
    @pytest.mark.asyncio
    async def test_list_workspaces(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListWorkspacesConfig(), credentials=credentials)
        )
        result = await _run(node, 200, {"entries": [{"workspaceId": "ws_1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_workspaces"

    @pytest.mark.asyncio
    async def test_create_workspace(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaCreateWorkspaceConfig(name="Analytics"), credentials=credentials)
        )
        result = await _run(node, 201, {"workspaceId": "ws_new"})
        assert result["status"] == "success"
        assert result["action"] == "create_workspace"
        assert result["data"]["workspaceId"] == "ws_new"

    @pytest.mark.asyncio
    async def test_add_workspace_grant(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaAddWorkspaceGrantConfig(
                    workspace_id="ws_1", grantee_id="u_1", grantee_type="member", permission="view"
                ),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"granted": True})
        assert result["status"] == "success"
        assert result["action"] == "add_workspace_grant"


# ============================================================================
# Catalog
# ============================================================================


class TestSigmaCatalogMock:
    @pytest.mark.asyncio
    async def test_list_files(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListFilesConfig(), credentials=credentials)
        )
        result = await _run(node, 200, {"entries": [{"id": "f_1", "type": "workbook"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_files"

    @pytest.mark.asyncio
    async def test_list_data_models(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListDataModelsConfig(), credentials=credentials)
        )
        result = await _run(node, 200, {"entries": [{"dataModelId": "dm_1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_data_models"

    @pytest.mark.asyncio
    async def test_get_data_model_spec(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaGetDataModelSpecConfig(data_model_id="dm_1"), credentials=credentials
            )
        )
        result = await _run(node, 200, {"spec": "version: 1"})
        assert result["status"] == "success"
        assert result["action"] == "get_data_model_spec"

    @pytest.mark.asyncio
    async def test_list_account_types(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListAccountTypesConfig(), credentials=credentials)
        )
        result = await _run(node, 200, {"entries": [{"name": "Admin"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_account_types"

    @pytest.mark.asyncio
    async def test_list_api_credentials(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListApiCredentialsConfig(), credentials=credentials)
        )
        result = await _run(node, 200, {"entries": [{"clientId": "sigma_client_123"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_api_credentials"


# ============================================================================
# Error handling
# ============================================================================


class TestSigmaErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, credentials):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaGetWorkbookConfig(workbook_id="missing"), credentials=credentials)
        )
        result = await _run(node, 404, {"message": "Workbook not found"})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_token_failure(self, credentials):
        """A failed token exchange surfaces a structured 401 error, not a crash."""
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListWorkbooksConfig(), credentials=credentials)
        )
        with patch(
            "nodes.sigma_node._sigma_get_token",
            side_effect=RuntimeError("Sigma token request failed (401): invalid_client"),
        ):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 401
        assert "invalid_client" in str(result["error"])

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        node = create_sigma_node(
            SigmaNodeConfig(config=SigmaListWorkbooksConfig(), credentials=None)
        )
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestSigmaDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_workbook_options(self):
        with patch(
            "nodes.sigma_node._sigma_get_token", return_value="mock_token"
        ), patch(
            "nodes.sigma_node._sigma_request",
            return_value={
                "status": "success",
                "data": {"entries": [{"workbookId": "wb_1", "name": "Sales"}]},
            },
        ):
            result = await SigmaNode.load_field_options(
                "workbook_id",
                credential_data={
                    "client_id": "sigma_client_123",
                    "client_secret": "sigma_secret_456",
                    "region": "aws-us-west",
                },
            )
        assert "options" in result
        assert result["options"][0]["value"] == "wb_1"
        assert result["options"][0]["label"] == "Sales"


# ============================================================================
# Trigger (poll-based: on_export_completed)
# ============================================================================


def _bind_state(node, initial=None):
    """Give a node an in-memory fake of the CAS node-state primitive so the
    seen-id cursor persists across polls within a single test.

    Applies the mutator against the in-memory store exactly like the real
    ``_update_node_state`` (loads state, applies mutator, writes when the mutator
    returns a non-None new_state), minus the DB + retry."""
    store = dict(initial or {})

    async def _update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(store))
        if new_state is not None:
            store.clear()
            store.update(new_state)
        return result

    node._update_node_state = _update
    return store


class TestSigmaTriggerResolvePayload:
    def test_resolve_returns_none_for_poll_op(self):
        """Poll trigger: resolve_trigger_payload returns None so execute() runs."""
        out = SigmaNode.resolve_trigger_payload(
            {"some": "webhook payload"}, {"operation": "on_export_completed"}
        )
        assert out is None

    def test_resolve_passthrough_for_normal_op(self):
        """Non-trigger op: payload passes through unchanged."""
        payload = {"some": "webhook payload"}
        out = SigmaNode.resolve_trigger_payload(payload, {"operation": "list_workbooks"})
        assert out == payload


class TestSigmaTriggerExecuteMock:
    @pytest.mark.asyncio
    async def test_first_poll_baselines_and_emits_nothing(self, credentials):
        """First poll records existing materializations as seen and emits nothing,
        so the trigger only fires for exports that complete afterward."""
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaOnExportCompletedConfig(workbook_id="wb_1"),
                credentials=credentials,
            )
        )
        _bind_state(node)
        result = await _run(
            node,
            200,
            {
                "entries": [
                    {"materializationId": "m_1", "status": "ready"},
                    {"materializationId": "m_2", "status": "ready"},
                ]
            },
        )
        assert result["status"] == "success"
        assert result["operation"] == "on_export_completed"
        assert result["new_count"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_second_poll_emits_only_new_and_dedupes(self, credentials):
        """After baselining, a new completed materialization is emitted once; a
        repeat poll with the same data emits nothing (dedup via the cursor)."""
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaOnExportCompletedConfig(workbook_id="wb_1"),
                credentials=credentials,
            )
        )
        _bind_state(node)

        # Poll 1: baseline on m_1.
        first = await _run(node, 200, {"entries": [{"materializationId": "m_1", "status": "ready"}]})
        assert first["new_count"] == 0

        # Poll 2: m_2 is newly completed -> emitted exactly once.
        second = await _run(
            node,
            200,
            {
                "entries": [
                    {"materializationId": "m_1", "status": "ready"},
                    {"materializationId": "m_2", "status": "ready"},
                ]
            },
        )
        assert second["new_count"] == 1
        assert [m["materializationId"] for m in second["items"]] == ["m_2"]

        # Poll 3: same data, nothing new -> dedupes to zero.
        third = await _run(
            node,
            200,
            {
                "entries": [
                    {"materializationId": "m_1", "status": "ready"},
                    {"materializationId": "m_2", "status": "ready"},
                ]
            },
        )
        assert third["new_count"] == 0
        assert third["items"] == []

    @pytest.mark.asyncio
    async def test_status_filter_excludes_incomplete(self, credentials):
        """Materializations that have not finished are not emitted."""
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaOnExportCompletedConfig(workbook_id="wb_1", status_filter="ready"),
                credentials=credentials,
            )
        )
        _bind_state(node)
        # Baseline empty (no completed entries yet).
        await _run(node, 200, {"entries": [{"materializationId": "m_1", "status": "building"}]})
        # m_1 finishes -> emitted; m_2 still building -> excluded.
        result = await _run(
            node,
            200,
            {
                "entries": [
                    {"materializationId": "m_1", "status": "ready"},
                    {"materializationId": "m_2", "status": "building"},
                ]
            },
        )
        assert result["new_count"] == 1
        assert [m["materializationId"] for m in result["items"]] == ["m_1"]

    @pytest.mark.asyncio
    async def test_poll_api_error_surfaces(self, credentials):
        """An API failure during the poll surfaces a structured error."""
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaOnExportCompletedConfig(workbook_id="wb_1"),
                credentials=credentials,
            )
        )
        _bind_state(node)
        result = await _run(node, 404, {"message": "Workbook not found"})
        assert result["status"] == "error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_state_blip_skips_tick_without_emitting(self, credentials):
        """A transient node-state I/O failure skips the tick cleanly: the API
        fetch succeeds but the CAS write can't happen, so nothing is emitted and
        the scheduled run neither fails nor re-baselines (state untouched)."""
        node = create_sigma_node(
            SigmaNodeConfig(
                config=SigmaOnExportCompletedConfig(workbook_id="wb_1"),
                credentials=credentials,
            )
        )

        async def _update(mutator, *, max_retries=4, skip_result=None):
            # Simulate _update_node_state's skip path: state I/O failed, so the
            # mutator is never applied and skip_result is returned untouched.
            return skip_result

        node._update_node_state = _update
        result = await _run(
            node,
            200,
            {"entries": [{"materializationId": "m_1", "status": "ready"}]},
        )
        assert result["status"] == "success"
        assert result["new_count"] == 0
        assert result["items"] == []
        assert node.trigger_produced_no_event(result) is True
