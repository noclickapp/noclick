"""
Mock tests for the Google Looker API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Auth/Profile: logout, get current user
- Queries: run inline, create, run by id, async start, async results
- Looks: search, get, run, create, update, delete
- Dashboards: search, get, create, update, delete, render, render results
- Users: search, create, update, delete
- Content: search folders, list connections, search alerts
- Scheduled plans: create, run once
- Error handling: API errors, missing credentials
- Dynamic options: LookML model dropdown

The Looker request helper performs a POST /login (returning an access token)
before each data request, so the mock client must answer both `.post()` (login)
and `.request()` (data) calls.
"""

import pytest
from unittest.mock import Mock, patch

from nodes.looker_node import (
    LookerNode,
    LookerNodeConfig,
    LookerApiKeyCredential,
    LookerLogoutConfig,
    LookerGetCurrentUserConfig,
    LookerRunInlineQueryConfig,
    LookerCreateQueryConfig,
    LookerRunQueryConfig,
    LookerRunQueryAsyncConfig,
    LookerGetQueryTaskResultsConfig,
    LookerSearchLooksConfig,
    LookerGetLookConfig,
    LookerRunLookConfig,
    LookerCreateLookConfig,
    LookerUpdateLookConfig,
    LookerDeleteLookConfig,
    LookerSearchDashboardsConfig,
    LookerGetDashboardConfig,
    LookerCreateDashboardConfig,
    LookerUpdateDashboardConfig,
    LookerDeleteDashboardConfig,
    LookerCreateRenderTaskConfig,
    LookerGetRenderTaskConfig,
    LookerSearchUsersConfig,
    LookerCreateUserConfig,
    LookerUpdateUserConfig,
    LookerDeleteUserConfig,
    LookerSearchFoldersConfig,
    LookerListConnectionsConfig,
    LookerSearchAlertsConfig,
    LookerCreateScheduledPlanConfig,
    LookerRunScheduledPlanOnceConfig,
    LookerGetQueryConfig,
    LookerGetQueryTaskConfig,
    LookerCreateSqlQueryConfig,
    LookerRunSqlQueryConfig,
    LookerGetLookmlModelConfig,
    LookerGetExploreConfig,
    LookerSearchContentConfig,
    LookerGetAlertConfig,
    LookerDeleteAlertConfig,
    LookerListScheduledPlansConfig,
    LookerGetScheduledPlanConfig,
    LookerDeleteScheduledPlanConfig,
    LookerOnLookResultsConfig,
)


def api_key_credentials_factory():
    return LookerApiKeyCredential(
        instance_url="https://acme.cloud.looker.com:19999",
        client_id="abc123",
        client_secret="secret456",
    )


@pytest.fixture
def api_key_credentials():
    return api_key_credentials_factory()


def create_looker_node(config):
    return LookerNode(
        node_id="test-looker-node",
        node_type="automation-looker",
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
    mock_response.headers = {"content-type": "application/json"}
    mock_response.text = ""
    payload = json_data if json_data is not None else {}
    mock_response.content = b'{"x": 1}'
    mock_response.json = lambda: payload
    return mock_response


def create_mock_client(status_code=200, json_data=None, login_token="tok_123", text_body=None):
    """Mock httpx.AsyncClient answering both login (.post) and data (.request).

    Works as an async context manager. `.post()` always returns the login token;
    `.request()` returns the data response with the configured status/payload.
    """
    data_response = create_mock_response(status_code, json_data)
    if text_body is not None:
        data_response.headers = {"content-type": "text/csv"}
        data_response.content = text_body.encode()
        data_response.text = text_body
    login_response = create_mock_response(200, {"access_token": login_token, "expires_in": 3600})
    mock_client = Mock()

    async def async_post(*args, **kwargs):
        return login_response

    async def async_request(*args, **kwargs):
        return data_response

    mock_client.post = async_post
    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


# ============================================================================
# Auth / Profile
# ============================================================================


class TestLookerAuthMock:
    @pytest.mark.asyncio
    async def test_logout(self, api_key_credentials):
        config = LookerNodeConfig(config=LookerLogoutConfig(), credentials=api_key_credentials)
        node = create_looker_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "logout"

    @pytest.mark.asyncio
    async def test_get_current_user(self, api_key_credentials):
        config = LookerNodeConfig(config=LookerGetCurrentUserConfig(), credentials=api_key_credentials)
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": 5, "email": "ada@acme.com"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_current_user"
        assert result["data"]["email"] == "ada@acme.com"


# ============================================================================
# Queries
# ============================================================================


class TestLookerQueriesMock:
    @pytest.mark.asyncio
    async def test_run_inline_query(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerRunInlineQueryConfig(
                model="ecommerce",
                view="orders",
                fields="orders.count,users.state",
                filters='{"orders.created_date":"30 days"}',
                sorts="orders.count desc",
                limit="100",
                result_format="json",
            ),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, [{"orders.count": 42}])
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "run_inline_query"
        assert result["data"][0]["orders.count"] == 42

    @pytest.mark.asyncio
    async def test_create_query(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerCreateQueryConfig(
                model="ecommerce", view="orders", fields="orders.count"
            ),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": 777})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_query"
        assert result["data"]["id"] == 777

    @pytest.mark.asyncio
    async def test_run_query(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerRunQueryConfig(query_id="777", result_format="csv"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, text_body="a,b\n1,2")
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "run_query"

    @pytest.mark.asyncio
    async def test_run_query_async(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerRunQueryAsyncConfig(query_id="777"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": "task_abc"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "run_query_async"
        assert result["data"]["id"] == "task_abc"

    @pytest.mark.asyncio
    async def test_get_query_task_results(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerGetQueryTaskResultsConfig(query_task_id="task_abc"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, [{"orders.count": 1}])
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_query_task_results"


# ============================================================================
# Looks
# ============================================================================


class TestLookerLooksMock:
    @pytest.mark.asyncio
    async def test_search_looks(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerSearchLooksConfig(title="Revenue%", limit="10"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, [{"id": 3, "title": "Revenue"}])
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_looks"
        assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_get_look(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerGetLookConfig(look_id="3"), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": 3, "title": "Revenue"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_look"
        assert result["data"]["id"] == 3

    @pytest.mark.asyncio
    async def test_run_look(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerRunLookConfig(look_id="3", result_format="json"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, [{"revenue": 1000}])
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "run_look"

    @pytest.mark.asyncio
    async def test_create_look(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerCreateLookConfig(title="New Look", query_id="777", folder_id="12"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": 9, "title": "New Look"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_look"
        assert result["data"]["id"] == 9

    @pytest.mark.asyncio
    async def test_update_look(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerUpdateLookConfig(look_id="9", title="Renamed", deleted="false"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": 9, "title": "Renamed"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_look"
        assert result["data"]["title"] == "Renamed"

    @pytest.mark.asyncio
    async def test_delete_look(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerDeleteLookConfig(look_id="9"), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_look"


# ============================================================================
# Dashboards
# ============================================================================


class TestLookerDashboardsMock:
    @pytest.mark.asyncio
    async def test_search_dashboards(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerSearchDashboardsConfig(title="KPI"), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, [{"id": "11", "title": "KPI"}])
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_dashboards"

    @pytest.mark.asyncio
    async def test_get_dashboard(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerGetDashboardConfig(dashboard_id="11"), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": "11", "title": "KPI"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_dashboard"
        assert result["data"]["id"] == "11"

    @pytest.mark.asyncio
    async def test_create_dashboard(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerCreateDashboardConfig(title="New Dash", folder_id="12"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": "22", "title": "New Dash"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_dashboard"

    @pytest.mark.asyncio
    async def test_update_dashboard(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerUpdateDashboardConfig(dashboard_id="22", title="Renamed Dash"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": "22", "title": "Renamed Dash"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_dashboard"

    @pytest.mark.asyncio
    async def test_delete_dashboard(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerDeleteDashboardConfig(dashboard_id="22"), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_dashboard"

    @pytest.mark.asyncio
    async def test_create_render_task(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerCreateRenderTaskConfig(dashboard_id="11", result_format="pdf"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": "render_1", "status": "enqueued_for_render"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_render_task"
        assert result["data"]["id"] == "render_1"

    @pytest.mark.asyncio
    async def test_get_render_task(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerGetRenderTaskConfig(render_task_id="render_1"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"status": "success"})
        original_request = mock_client.request

        async def render_request(*args, **kwargs):
            response = await original_request(*args, **kwargs)
            response.headers = {"content-type": "application/pdf"}
            response.content = b"%PDF-1.7 synthetic"
            return response

        mock_client.request = render_request
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_render_task"
        assert result["data"].data == b"%PDF-1.7 synthetic"


# ============================================================================
# Users
# ============================================================================


class TestLookerUsersMock:
    @pytest.mark.asyncio
    async def test_search_users(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerSearchUsersConfig(email="ada@acme.com"), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, [{"id": 5, "email": "ada@acme.com"}])
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_users"

    @pytest.mark.asyncio
    async def test_create_user(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerCreateUserConfig(first_name="Ada", last_name="Lovelace", email="ada@acme.com"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": 6, "first_name": "Ada"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_user"
        assert result["data"]["id"] == 6

    @pytest.mark.asyncio
    async def test_update_user(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerUpdateUserConfig(user_id="6", first_name="Augusta", is_disabled="true"),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": 6, "first_name": "Augusta"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_user"

    @pytest.mark.asyncio
    async def test_delete_user(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerDeleteUserConfig(user_id="6"), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_user"


# ============================================================================
# Content
# ============================================================================


class TestLookerContentMock:
    @pytest.mark.asyncio
    async def test_search_folders(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerSearchFoldersConfig(name="Shared"), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, [{"id": "12", "name": "Shared"}])
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_folders"

    @pytest.mark.asyncio
    async def test_list_connections(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerListConnectionsConfig(), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, [{"name": "bigquery_prod"}])
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_connections"

    @pytest.mark.asyncio
    async def test_search_alerts(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerSearchAlertsConfig(limit="20"), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, [{"id": 1, "custom_title": "Revenue drop"}])
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_alerts"


# ============================================================================
# Scheduled plans
# ============================================================================


class TestLookerScheduledPlansMock:
    @pytest.mark.asyncio
    async def test_create_scheduled_plan(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerCreateScheduledPlanConfig(
                name="Daily revenue",
                dashboard_id="11",
                crontab="0 9 * * *",
                destination_address="team@acme.com",
                result_format="pdf",
            ),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": 50, "name": "Daily revenue"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_scheduled_plan"
        assert result["data"]["id"] == 50

    @pytest.mark.asyncio
    async def test_run_scheduled_plan_once(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerRunScheduledPlanOnceConfig(
                name="One-off",
                look_id="3",
                destination_address="me@acme.com",
                result_format="csv",
            ),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, {"id": 51})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "run_scheduled_plan_once"


# ============================================================================
# Error handling
# ============================================================================


class TestLookerErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerGetLookConfig(look_id="missing"), credentials=api_key_credentials
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(404, {"message": "Not found"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert result["error"] == "Looker request failed (404)"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = LookerNodeConfig(config=LookerGetCurrentUserConfig(), credentials=None)
        node = create_looker_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_invalid_filters_json(self, api_key_credentials):
        config = LookerNodeConfig(
            config=LookerRunInlineQueryConfig(
                model="ecommerce", view="orders", fields="orders.count", filters="{not json}"
            ),
            credentials=api_key_credentials,
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(200, [])
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            with pytest.raises(ValueError, match="Filters must be valid JSON"):
                await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestLookerDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_dispatcher_contract_and_dependent_explores(self):
        cred = {"instance_url": "https://acme.cloud.looker.com:19999", "client_id": "a", "client_secret": "b"}
        with patch("nodes.looker_node._looker_request", return_value={
            "status": "success", "data": {"explores": [
                {"name": "orders", "label": "Orders"}, {"name": "users", "label": None}
            ]},
        }) as request:
            options = await LookerNode.load_field_options(
                field_name="view", credential_data=cred,
                context={"config": {"model": "ecommerce"}}, search="ORDER",
            )
        assert options == [{"label": "Orders", "value": "orders"}]
        assert request.call_args.args[2] == "/lookml_models/ecommerce"

    @pytest.mark.asyncio
    async def test_picker_preserves_provider_error(self):
        with patch("nodes.looker_node._looker_request", return_value={
            "status": "error", "error": "Looker request failed (403)",
        }):
            with pytest.raises(ValueError, match="403"):
                await LookerNode.load_field_options(
                    field_name="look_id", credential_data={"client_id": "a"}
                )

    @pytest.mark.asyncio
    async def test_picker_rejects_malformed_rows(self):
        with patch("nodes.looker_node._looker_request", return_value={
            "status": "success", "data": [{"unexpected": "x"}],
        }):
            with pytest.raises(ValueError, match="invalid options"):
                await LookerNode.load_field_options(
                    field_name="folder_id", credential_data={"client_id": "a"}
                )

    @pytest.mark.asyncio
    async def test_picker_missing_inputs(self):
        with pytest.raises(ValueError, match="Connect a Looker account"):
            await LookerNode.load_field_options("look_id")
        assert await LookerNode.load_field_options("view", credential_data={"client_id": "a"}) == []
        assert await LookerNode.load_field_options("unknown", credential_data={"client_id": "a"}) == []


# ============================================================================
# New coverage: SQL Runner, LookML metadata, content, alert/plan lifecycle
# ============================================================================


def create_capturing_client(status_code=200, json_data=None, login_token="tok_123"):
    """Like create_mock_client but records the data request's (method, url, ...)
    into the returned `captured` dict so tests can assert the endpoint."""
    data_response = create_mock_response(status_code, json_data)
    login_response = create_mock_response(200, {"access_token": login_token, "expires_in": 3600})
    captured: dict = {}
    mock_client = Mock()

    async def async_post(*args, **kwargs):
        return login_response

    async def async_request(*args, **kwargs):
        captured["method"] = kwargs.get("method") or (args[0] if args else None)
        captured["url"] = kwargs.get("url")
        captured["params"] = kwargs.get("params")
        captured["json"] = kwargs.get("json")
        return data_response

    mock_client.post = async_post
    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client, captured


class TestLookerNewCoverageMock:
    async def _run_capture(self, op, status_code=200, json_data=None):
        config = LookerNodeConfig(config=op, credentials=api_key_credentials_factory())
        node = create_looker_node(config)
        client, captured = create_capturing_client(status_code, json_data or {"ok": True})
        with patch("nodes.looker_node.guarded_async_client", return_value=client):
            result = await node.execute({})
        return result, captured

    @pytest.mark.asyncio
    async def test_get_query(self):
        result, cap = await self._run_capture(LookerGetQueryConfig(query_id="7"))
        assert result["status"] == "success"
        assert cap["method"] == "GET" and cap["url"].endswith("/api/4.0/queries/7")

    @pytest.mark.asyncio
    async def test_get_query_task(self):
        result, cap = await self._run_capture(LookerGetQueryTaskConfig(query_task_id="qt1"))
        assert cap["method"] == "GET" and cap["url"].endswith("/query_tasks/qt1")

    @pytest.mark.asyncio
    async def test_create_sql_query(self):
        result, cap = await self._run_capture(
            LookerCreateSqlQueryConfig(connection_name="warehouse", sql="SELECT 1")
        )
        assert cap["method"] == "POST" and cap["url"].endswith("/sql_queries")
        assert cap["json"] == {"connection_name": "warehouse", "sql": "SELECT 1"}

    @pytest.mark.asyncio
    async def test_create_sql_query_requires_connection_or_model(self):
        config = LookerNodeConfig(
            config=LookerCreateSqlQueryConfig(sql="SELECT 1"),
            credentials=api_key_credentials_factory(),
        )
        node = create_looker_node(config)
        client, _ = create_capturing_client()
        with patch("nodes.looker_node.guarded_async_client", return_value=client):
            with pytest.raises(ValueError, match="connection or a model"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_run_sql_query(self):
        result, cap = await self._run_capture(
            LookerRunSqlQueryConfig(slug="abc123", result_format="csv")
        )
        assert cap["method"] == "POST" and cap["url"].endswith("/sql_queries/abc123/run/csv")

    @pytest.mark.asyncio
    async def test_get_lookml_model(self):
        result, cap = await self._run_capture(LookerGetLookmlModelConfig(model="ecommerce"))
        assert cap["method"] == "GET" and cap["url"].endswith("/lookml_models/ecommerce")

    @pytest.mark.asyncio
    async def test_get_explore(self):
        result, cap = await self._run_capture(
            LookerGetExploreConfig(model="ecommerce", explore="orders")
        )
        assert cap["url"].endswith("/lookml_models/ecommerce/explores/orders")

    @pytest.mark.asyncio
    async def test_search_content(self):
        result, cap = await self._run_capture(LookerSearchContentConfig(terms="revenue"))
        assert cap["method"] == "GET" and cap["url"].endswith("/content/revenue")

    @pytest.mark.asyncio
    async def test_get_alert(self):
        result, cap = await self._run_capture(LookerGetAlertConfig(alert_id="a1"))
        assert cap["method"] == "GET" and cap["url"].endswith("/alerts/a1")

    @pytest.mark.asyncio
    async def test_delete_alert(self):
        result, cap = await self._run_capture(LookerDeleteAlertConfig(alert_id="a1"))
        assert cap["method"] == "DELETE" and cap["url"].endswith("/alerts/a1")

    @pytest.mark.asyncio
    async def test_list_scheduled_plans(self):
        result, cap = await self._run_capture(
            LookerListScheduledPlansConfig(all_users="true"), json_data=[{"id": "1"}]
        )
        assert cap["method"] == "GET" and cap["url"].endswith("/scheduled_plans")
        assert cap["params"] == {"all_users": True}

    @pytest.mark.asyncio
    async def test_get_scheduled_plan(self):
        result, cap = await self._run_capture(LookerGetScheduledPlanConfig(scheduled_plan_id="9"))
        assert cap["method"] == "GET" and cap["url"].endswith("/scheduled_plans/9")

    @pytest.mark.asyncio
    async def test_delete_scheduled_plan(self):
        result, cap = await self._run_capture(LookerDeleteScheduledPlanConfig(scheduled_plan_id="9"))
        assert cap["method"] == "DELETE" and cap["url"].endswith("/scheduled_plans/9")


# ============================================================================
# Trigger (poll-based: on_look_results)
# ============================================================================


async def _run_trigger(node, status_code, json_data, state_store):
    """Execute the poll trigger with httpx + the node's persistent state mocked.

    The same `state_store` dict is shared across calls so baseline + dedup
    across polls can be exercised (matches ScheduledPollTriggerMixin's
    _load_node_state/_save_node_state seam)."""
    mock_client = create_mock_client(status_code, json_data)

    async def fake_load_state(self):
        return dict(state_store)

    async def fake_save_state(self, state, *, expected_version=None):
        state_store.clear()
        state_store.update(state)

    with patch(
        "nodes.looker_node.guarded_async_client", return_value=mock_client
    ), patch.object(
        LookerNode, "_load_node_state", fake_load_state
    ), patch.object(
        LookerNode, "_save_node_state", fake_save_state
    ):
        return await node.execute({})


class TestLookerTriggerMock:
    def test_resolve_trigger_payload_returns_none_for_trigger(self):
        """The cron POST is a wake-up signal: the poll mixin returns None so
        execute() runs and actually runs the Look."""
        assert (
            LookerNode.resolve_trigger_payload(
                {"any": "payload"}, {"operation": "on_look_results"}
            )
            is None
        )

    def test_base_resolve_trigger_payload_passthrough(self):
        """The generic (non-poll) contract is to pass the payload through — the
        poll mixin deliberately overrides this to None for the wake-up signal."""
        from nodes.core.base import WorkflowNode

        payload = {"data": [1, 2, 3]}
        assert (
            WorkflowNode.resolve_trigger_payload(payload, {"operation": "run_look"})
            is payload
        )

    @pytest.mark.asyncio
    async def test_poll_baselines_then_emits_new_and_dedupes(self):
        """First poll baselines (emits nothing); a later poll emits only the
        newly-appeared row; re-polling the same rows emits nothing. Dedup is by
        the whole row when no cursor_field is set, persisted in node state."""
        config = LookerNodeConfig(
            config=LookerOnLookResultsConfig(look_id="42"),
            credentials=api_key_credentials_factory(),
        )
        node = create_looker_node(config)
        state_store: dict = {}

        base = [{"orders.id": "1"}, {"orders.id": "2"}]
        result = await _run_trigger(node, 200, base, state_store)
        assert result["status"] == "success"
        assert result["operation"] == "on_look_results"
        assert result["new_count"] == 0
        assert result["items"] == []

        grown = [{"orders.id": "1"}, {"orders.id": "2"}, {"orders.id": "3"}]
        result = await _run_trigger(node, 200, grown, state_store)
        assert result["new_count"] == 1
        assert result["items"] == [{"orders.id": "3"}]

        result = await _run_trigger(node, 200, grown, state_store)
        assert result["new_count"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_poll_with_cursor_field_dedupes_by_that_key(self):
        """cursor_field selects the de-dup key: a new cursor value is emitted
        once, then deduped on the next poll — persisted across polls via state."""
        op = LookerOnLookResultsConfig(look_id="42", cursor_field="orders.created_time")
        config = LookerNodeConfig(config=op, credentials=api_key_credentials_factory())
        node = create_looker_node(config)
        state_store: dict = {}

        base = [
            {"orders.id": "1", "orders.created_time": "2026-06-20T10:00:00"},
            {"orders.id": "2", "orders.created_time": "2026-06-20T11:00:00"},
        ]
        result = await _run_trigger(node, 200, base, state_store)
        assert result["new_count"] == 0  # baseline

        grown = base + [{"orders.id": "3", "orders.created_time": "2026-06-20T12:00:00"}]
        result = await _run_trigger(node, 200, grown, state_store)
        assert result["new_count"] == 1
        assert result["items"][0]["orders.created_time"] == "2026-06-20T12:00:00"

        # Re-poll the same rows -> nothing new (12:00 cursor already seen).
        result = await _run_trigger(node, 200, grown, state_store)
        assert result["new_count"] == 0

    @pytest.mark.asyncio
    async def test_poll_api_error_propagates(self):
        """A Looker API error from running the Look is surfaced, not swallowed."""
        config = LookerNodeConfig(
            config=LookerOnLookResultsConfig(look_id="999"),
            credentials=api_key_credentials_factory(),
        )
        node = create_looker_node(config)
        mock_client = create_mock_client(404, {"message": "Look not found"})
        with patch("nodes.looker_node.guarded_async_client", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_load_field_value_provisions_webhook_and_schedule(self):
        """The current schedule registration seam supplies trigger mirrors."""
        with patch(
            "utils.webhook_manager.WebhookManager.reconcile_node",
            return_value={"values": {
                "webhook_id": "wh-1", "webhook_url": "https://hook.test/wh-1",
                "schedule_id": "sched-1", "next_run": "2026-06-20T12:05:00Z",
                "interval_ms": 5 * 60 * 1000,
                "is_active": True,
            }},
        ), patch(
            "utils.webhook_manager.WebhookManager.get_or_create_webhook",
            return_value={"webhook_id": "wh-1", "webhook_url": "https://hook.test/wh-1"},
        ):
            result = await LookerNode.load_field_value(
                "webhook_url",
                "user-1",
                "11111111-1111-1111-1111-111111111111",
                "node-1",
                Mock(),
                context={"schedule": {"frequency": "minutes", "interval": 5}},
            )
        values = result["values"]
        assert values["webhook_id"] == "wh-1"
        assert values["webhook_url"] == "https://hook.test/wh-1"
        assert values["schedule_id"] == "sched-1"
        assert values["next_run"] == "2026-06-20T12:05:00Z"
        assert values["interval_ms"] == 5 * 60 * 1000
        assert values["is_active"] is True

    @pytest.mark.asyncio
    async def test_load_field_value_non_trigger_field(self):
        """Non-webhook fields are not provisioned by load_field_value."""
        result = await LookerNode.load_field_value(
            "look_id",
            "user-1",
            "11111111-1111-1111-1111-111111111111",
            "node-1",
            Mock(),
        )
        assert result == {"value": None}
