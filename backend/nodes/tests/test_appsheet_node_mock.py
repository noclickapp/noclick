"""
Mock tests for the Google AppSheet REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Rows: add, edit, delete
- Find: by key, all rows, with Selector expression
- Actions: invoke custom action
- Triggers: on_rows_added/updated/deleted, on_data_change, on_schedule (passthrough)
- Error handling: API errors, missing credentials, malformed Rows JSON
- Request shape: correct Action/Properties body and region host
"""

import pytest
from unittest.mock import Mock, patch

from nodes.appsheet_node import (
    AppSheetNode,
    AppSheetNodeConfig,
    AppSheetApiKeyCredential,
    AppSheetAddRowsConfig,
    AppSheetEditRowsConfig,
    AppSheetDeleteRowsConfig,
    AppSheetFindRowsConfig,
    AppSheetFindAllRowsConfig,
    AppSheetFindWithSelectorConfig,
    AppSheetInvokeActionConfig,
    AppSheetOnRowsAddedConfig,
    AppSheetOnRowsUpdatedConfig,
    AppSheetOnRowsDeletedConfig,
    AppSheetOnDataChangeConfig,
    AppSheetOnScheduleConfig,
)


@pytest.fixture
def api_key_credentials():
    return AppSheetApiKeyCredential(
        app_id="app-123",
        application_access_key="V2-EXAMPLE_APPSHEET_APPLICATION_ACCESS_KEY",
        region="global",
    )


def create_appsheet_node(config):
    return AppSheetNode(
        node_id="test-appsheet-node",
        node_type="automation-appsheet",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, text=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text if text is not None else "[]"
    mock_response.json = lambda: (json_data if json_data is not None else [])
    return mock_response


def create_mock_client(status_code=200, json_data=None, text=None, capture=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager. Optionally records call kwargs in
    the `capture` dict."""
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


class TestAppSheetRowsMock:
    @pytest.mark.asyncio
    async def test_add_rows(self, api_key_credentials):
        config = AppSheetNodeConfig(
            config=AppSheetAddRowsConfig(
                table_name="People",
                rows='[{"FirstName": "Jane", "LastName": "Doe"}]',
            ),
            credentials=api_key_credentials,
        )
        node = create_appsheet_node(config)
        capture = {}
        mock_client = create_mock_client(
            200, [{"Id": "1", "FirstName": "Jane"}], capture=capture
        )
        with patch("nodes.appsheet_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "add_rows"
        assert result["data"][0]["FirstName"] == "Jane"
        # Verify request shape: correct URL, Action field, and Rows body.
        assert capture["url"] == (
            "https://www.appsheet.com/api/v2/apps/app-123/tables/People/Action"
        )
        assert capture["json"]["Action"] == "Add"
        assert capture["json"]["Rows"][0]["LastName"] == "Doe"
        assert capture["headers"]["ApplicationAccessKey"].startswith("V2-")

    @pytest.mark.asyncio
    async def test_edit_rows(self, api_key_credentials):
        config = AppSheetNodeConfig(
            config=AppSheetEditRowsConfig(
                table_name="People",
                rows='[{"Id": "1", "LastName": "Smith"}]',
                run_as_user_email="user@example.com",
            ),
            credentials=api_key_credentials,
        )
        node = create_appsheet_node(config)
        capture = {}
        mock_client = create_mock_client(200, [{"Id": "1", "LastName": "Smith"}], capture=capture)
        with patch("nodes.appsheet_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "edit_rows"
        assert capture["json"]["Action"] == "Edit"
        assert capture["json"]["Properties"]["RunAsUserEmail"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_delete_rows(self, api_key_credentials):
        config = AppSheetNodeConfig(
            config=AppSheetDeleteRowsConfig(table_name="People", rows='[{"Id": "1"}]'),
            credentials=api_key_credentials,
        )
        node = create_appsheet_node(config)
        capture = {}
        mock_client = create_mock_client(200, [{"Id": "1"}], capture=capture)
        with patch("nodes.appsheet_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_rows"
        assert capture["json"]["Action"] == "Delete"


class TestAppSheetFindMock:
    @pytest.mark.asyncio
    async def test_find_rows(self, api_key_credentials):
        config = AppSheetNodeConfig(
            config=AppSheetFindRowsConfig(table_name="People", rows='[{"Id": "1"}]'),
            credentials=api_key_credentials,
        )
        node = create_appsheet_node(config)
        capture = {}
        mock_client = create_mock_client(200, [{"Id": "1", "FirstName": "Jane"}], capture=capture)
        with patch("nodes.appsheet_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "find_rows"
        assert capture["json"]["Action"] == "Find"
        assert capture["json"]["Rows"] == [{"Id": "1"}]

    @pytest.mark.asyncio
    async def test_find_all_rows(self, api_key_credentials):
        config = AppSheetNodeConfig(
            config=AppSheetFindAllRowsConfig(table_name="People"),
            credentials=api_key_credentials,
        )
        node = create_appsheet_node(config)
        capture = {}
        mock_client = create_mock_client(200, [{"Id": "1"}, {"Id": "2"}], capture=capture)
        with patch("nodes.appsheet_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "find_all_rows"
        assert capture["json"]["Action"] == "Find"
        assert capture["json"]["Rows"] == []
        assert "Selector" not in capture["json"].get("Properties", {})
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_find_with_selector(self, api_key_credentials):
        config = AppSheetNodeConfig(
            config=AppSheetFindWithSelectorConfig(
                table_name="People", selector="Filter(People, [Age] >= 21)"
            ),
            credentials=api_key_credentials,
        )
        node = create_appsheet_node(config)
        capture = {}
        mock_client = create_mock_client(200, [{"Id": "1", "Age": 30}], capture=capture)
        with patch("nodes.appsheet_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "find_with_selector"
        assert capture["json"]["Action"] == "Find"
        assert capture["json"]["Properties"]["Selector"] == "Filter(People, [Age] >= 21)"


class TestAppSheetActionsMock:
    @pytest.mark.asyncio
    async def test_invoke_action(self, api_key_credentials):
        config = AppSheetNodeConfig(
            config=AppSheetInvokeActionConfig(
                table_name="Orders",
                action_name="Approve Order",
                rows='[{"Id": "42"}]',
            ),
            credentials=api_key_credentials,
        )
        node = create_appsheet_node(config)
        capture = {}
        mock_client = create_mock_client(200, [{"Id": "42", "Status": "Approved"}], capture=capture)
        with patch("nodes.appsheet_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "invoke_action"
        # Custom actions select via the action name in the Action field.
        assert capture["json"]["Action"] == "Approve Order"


class TestAppSheetRegionMock:
    @pytest.mark.asyncio
    async def test_eu_region_host(self):
        creds = AppSheetApiKeyCredential(
            app_id="app-eu", application_access_key="V2-key", region="eu"
        )
        config = AppSheetNodeConfig(
            config=AppSheetFindAllRowsConfig(table_name="People"), credentials=creds
        )
        node = create_appsheet_node(config)
        capture = {}
        mock_client = create_mock_client(200, [], capture=capture)
        with patch("nodes.appsheet_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert capture["url"] == (
            "https://eu.appsheet.com/api/v2/apps/app-eu/tables/People/Action"
        )


class TestAppSheetTriggerMock:
    @pytest.mark.parametrize(
        "config_cls,operation",
        [
            (AppSheetOnRowsAddedConfig, "on_rows_added"),
            (AppSheetOnRowsUpdatedConfig, "on_rows_updated"),
            (AppSheetOnRowsDeletedConfig, "on_rows_deleted"),
            (AppSheetOnDataChangeConfig, "on_data_change"),
            (AppSheetOnScheduleConfig, "on_schedule"),
        ],
    )
    @pytest.mark.asyncio
    async def test_trigger_passthrough(self, config_cls, operation):
        """Every AppSheet trigger passes the inbound webhook payload through as output."""
        config = AppSheetNodeConfig(
            config=config_cls(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_appsheet_node(config)
        payload = {"event": operation, "row": {"Id": "1"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == operation
        assert result["data"]["event"] == operation
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    def test_all_triggers_use_resolve_trigger_payload_default(self):
        """Push-fired triggers surface the payload via the base resolve_trigger_payload
        (no override) — the standard passive-receiver pattern."""
        from nodes.appsheet_node import AppSheetNode
        assert "resolve_trigger_payload" not in AppSheetNode.__dict__


class TestAppSheetErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = AppSheetNodeConfig(
            config=AppSheetFindAllRowsConfig(table_name="Missing"),
            credentials=api_key_credentials,
        )
        node = create_appsheet_node(config)
        mock_client = create_mock_client(
            403, {"message": "web API disabled or invalid access key"}, text="forbidden"
        )
        with patch("nodes.appsheet_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 403
        assert "access key" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = AppSheetNodeConfig(
            config=AppSheetFindAllRowsConfig(table_name="People"), credentials=None
        )
        node = create_appsheet_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_malformed_rows_json(self, api_key_credentials):
        config = AppSheetNodeConfig(
            config=AppSheetAddRowsConfig(table_name="People", rows="{not valid json"),
            credentials=api_key_credentials,
        )
        node = create_appsheet_node(config)
        with pytest.raises(ValueError, match="valid JSON array"):
            await node.execute({})
