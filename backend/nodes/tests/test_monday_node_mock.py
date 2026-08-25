"""
Mock tests for the monday.com GraphQL API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Boards: list, get, create
- Items: list, get by id, query by column, create, create subitem, change
  column value(s), change simple, move to group, move to board, archive,
  delete, duplicate
- Groups & Columns: create group, delete group, create column
- Updates & Notifications: create update, create notification
- Account: list users, get me, list workspaces
- Webhooks: create webhook, delete webhook
- Trigger: on_board_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: GraphQL body errors (HTTP 200 + errors array), missing creds
- Dynamic options: board dropdown

monday.com returns HTTP 200 with an ``errors`` array on GraphQL failures, so
the error test asserts that path (not an HTTP 4xx).
"""

import pytest
from unittest.mock import Mock, patch

from nodes.monday_node import (
    MondayNode,
    MondayNodeConfig,
    MondayApiTokenCredential,
    MondayOAuthCredential,
    MondayListBoardsConfig,
    MondayGetBoardConfig,
    MondayCreateBoardConfig,
    MondayListItemsConfig,
    MondayGetItemsConfig,
    MondayQueryItemsByColumnConfig,
    MondayCreateItemConfig,
    MondayCreateSubitemConfig,
    MondayChangeColumnValueConfig,
    MondayChangeMultipleColumnValuesConfig,
    MondayChangeSimpleColumnValueConfig,
    MondayMoveItemToGroupConfig,
    MondayMoveItemToBoardConfig,
    MondayArchiveItemConfig,
    MondayDeleteItemConfig,
    MondayDuplicateItemConfig,
    MondayCreateGroupConfig,
    MondayDeleteGroupConfig,
    MondayCreateColumnConfig,
    MondayCreateUpdateConfig,
    MondayCreateNotificationConfig,
    MondayListUsersConfig,
    MondayGetMeConfig,
    MondayListWorkspacesConfig,
    MondayCreateWebhookConfig,
    MondayDeleteWebhookConfig,
    MondayBoardEventTriggerConfig,
)


@pytest.fixture
def token_credentials():
    return MondayApiTokenCredential(api_token="monday_test_token_123")


def create_monday_node(config):
    return MondayNode(
        node_id="test-monday-node",
        node_type="automation-monday",
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


def _gql(data):
    """monday.com wraps GraphQL results in {data: {...}}."""
    return {"data": data}


class TestMondayBoardsMock:
    @pytest.mark.asyncio
    async def test_list_boards(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayListBoardsConfig(limit="10"), credentials=token_credentials
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"boards": [{"id": "1", "name": "Tasks"}, {"id": "2", "name": "CRM"}]})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_boards"
        assert len(result["data"]["boards"]) == 2

    @pytest.mark.asyncio
    async def test_get_board(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayGetBoardConfig(board_id="123"), credentials=token_credentials
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(200, _gql({"boards": [{"id": "123", "name": "Tasks"}]}))
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_board"
        assert result["data"]["boards"][0]["id"] == "123"

    @pytest.mark.asyncio
    async def test_create_board(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayCreateBoardConfig(board_name="New Board", board_kind="public"),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"create_board": {"id": "999", "name": "New Board"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_board"
        assert result["data"]["create_board"]["id"] == "999"


class TestMondayItemsMock:
    @pytest.mark.asyncio
    async def test_list_items(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayListItemsConfig(board_id="123", limit="50"),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200,
            _gql({"boards": [{"items_page": {"cursor": None, "items": [{"id": "i1"}]}}]}),
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_items"

    @pytest.mark.asyncio
    async def test_get_items(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayGetItemsConfig(item_ids="11,22"), credentials=token_credentials
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"items": [{"id": "11"}, {"id": "22"}]})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_items"
        assert len(result["data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_query_items_by_column(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayQueryItemsByColumnConfig(
                board_id="123", column_id="status", column_values="Done"
            ),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"items_page_by_column_values": {"cursor": None, "items": []}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "query_items_by_column"

    @pytest.mark.asyncio
    async def test_create_item(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayCreateItemConfig(
                board_id="123", item_name="Task A", group_id="topics"
            ),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"create_item": {"id": "i9", "name": "Task A"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_item"
        assert result["data"]["create_item"]["id"] == "i9"

    @pytest.mark.asyncio
    async def test_create_subitem(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayCreateSubitemConfig(parent_item_id="i9", item_name="Subtask"),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"create_subitem": {"id": "s1", "name": "Subtask"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_subitem"

    @pytest.mark.asyncio
    async def test_change_column_value(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayChangeColumnValueConfig(
                board_id="123", item_id="i9", column_id="status", value='{"label":"Done"}'
            ),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(200, _gql({"change_column_value": {"id": "i9"}}))
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "change_column_value"

    @pytest.mark.asyncio
    async def test_change_multiple_column_values(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayChangeMultipleColumnValuesConfig(
                board_id="123", item_id="i9", column_values='{"status":{"label":"Done"}}'
            ),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"change_multiple_column_values": {"id": "i9"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "change_multiple_column_values"

    @pytest.mark.asyncio
    async def test_change_simple_column_value(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayChangeSimpleColumnValueConfig(
                board_id="123", item_id="i9", column_id="text", value="hello"
            ),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"change_simple_column_value": {"id": "i9"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "change_simple_column_value"

    @pytest.mark.asyncio
    async def test_move_item_to_group(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayMoveItemToGroupConfig(item_id="i9", group_id="done"),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(200, _gql({"move_item_to_group": {"id": "i9"}}))
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "move_item_to_group"

    @pytest.mark.asyncio
    async def test_move_item_to_board(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayMoveItemToBoardConfig(item_id="i9", board_id="456", group_id="g1"),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(200, _gql({"move_item_to_board": {"id": "i9"}}))
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "move_item_to_board"

    @pytest.mark.asyncio
    async def test_archive_item(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayArchiveItemConfig(item_id="i9"), credentials=token_credentials
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(200, _gql({"archive_item": {"id": "i9"}}))
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "archive_item"

    @pytest.mark.asyncio
    async def test_delete_item(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayDeleteItemConfig(item_id="i9"), credentials=token_credentials
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(200, _gql({"delete_item": {"id": "i9"}}))
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_item"

    @pytest.mark.asyncio
    async def test_duplicate_item(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayDuplicateItemConfig(board_id="123", item_id="i9"),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"duplicate_item": {"id": "i10", "name": "Task A (copy)"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "duplicate_item"


class TestMondayGroupsColumnsMock:
    @pytest.mark.asyncio
    async def test_create_group(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayCreateGroupConfig(board_id="123", group_name="Sprint 1"),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"create_group": {"id": "g1", "title": "Sprint 1"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_group"

    @pytest.mark.asyncio
    async def test_delete_group(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayDeleteGroupConfig(board_id="123", group_id="g1"),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(200, _gql({"delete_group": {"id": "g1"}}))
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_group"

    @pytest.mark.asyncio
    async def test_create_column(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayCreateColumnConfig(
                board_id="123", title="Priority", column_type="status"
            ),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"create_column": {"id": "c1", "title": "Priority", "type": "status"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_column"


class TestMondayUpdatesNotificationsMock:
    @pytest.mark.asyncio
    async def test_create_update(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayCreateUpdateConfig(item_id="i9", body="Looks good!"),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"create_update": {"id": "u1", "body": "Looks good!"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_update"

    @pytest.mark.asyncio
    async def test_create_notification(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayCreateNotificationConfig(
                user_id="u1", target_id="i9", target_type="Project", text="Ping"
            ),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"create_notification": {"id": "n1", "text": "Ping"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_notification"


class TestMondayAccountMock:
    @pytest.mark.asyncio
    async def test_list_users(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayListUsersConfig(limit="10"), credentials=token_credentials
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"users": [{"id": "1", "name": "Ada", "email": "ada@example.com"}]})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_users"

    @pytest.mark.asyncio
    async def test_get_me(self, token_credentials):
        config = MondayNodeConfig(config=MondayGetMeConfig(), credentials=token_credentials)
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"me": {"id": "1", "name": "Ada", "email": "ada@example.com"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_me"
        assert result["data"]["me"]["name"] == "Ada"

    @pytest.mark.asyncio
    async def test_get_me_with_oauth_credential(self):
        """OAuth access tokens are sent as the bare Authorization header too."""
        config = MondayNodeConfig(
            config=MondayGetMeConfig(),
            credentials=MondayOAuthCredential(access_token="oauth_tok_456"),
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(200, _gql({"me": {"id": "2", "name": "Grace"}}))
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["data"]["me"]["name"] == "Grace"

    @pytest.mark.asyncio
    async def test_list_workspaces(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayListWorkspacesConfig(limit="5"), credentials=token_credentials
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"workspaces": [{"id": "w1", "name": "Main"}]})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_workspaces"


class TestMondayWebhooksMock:
    @pytest.mark.asyncio
    async def test_create_webhook(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayCreateWebhookConfig(
                board_id="123", url="https://abc.hooks.example.test", event="create_item"
            ),
            credentials=token_credentials,
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"create_webhook": {"id": "wh1", "board_id": "123"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_webhook"
        assert result["data"]["create_webhook"]["id"] == "wh1"

    @pytest.mark.asyncio
    async def test_delete_webhook(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayDeleteWebhookConfig(webhook_id="wh1"), credentials=token_credentials
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, _gql({"delete_webhook": {"id": "wh1", "board_id": "123"}})
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_webhook"


class TestMondayTriggerMock:
    @pytest.mark.asyncio
    async def test_on_board_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = MondayNodeConfig(
            config=MondayBoardEventTriggerConfig(
                board_id="123", event="create_item", webhook_url="https://abc.hooks.example.test"
            ),
            credentials=None,
        )
        node = create_monday_node(config)
        payload = {"event": {"type": "create_item", "pulseId": 999}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_board_event"
        assert result["data"]["event"]["pulseId"] == 999

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.monday_node._monday_graphql",
            return_value={
                "status": "success",
                "data": {"create_webhook": {"id": "wh99", "board_id": "123"}},
            },
        ) as mock_req:
            extra = await MondayNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_token": "monday_test"},
                config={"board_id": "123", "event": "create_item"},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "wh99"
        assert extra["signing_secret"]

    @pytest.mark.asyncio
    async def test_register_external_webhook_requires_board(self):
        with pytest.raises(ValueError, match="board must be selected"):
            await MondayNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_token": "monday_test"},
                config={},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.monday_node._monday_graphql",
            return_value={"status": "success", "data": {"delete_webhook": {"id": "wh99"}}},
        ) as mock_req:
            await MondayNode._unregister_external_webhook(
                credential={"api_token": "monday_test"},
                config={"external_webhook_id": "wh99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        # monday.com does not sign webhook payloads (challenge handshake only);
        # inbound event payloads are accepted.
        assert MondayNode.verify_webhook_signature(b'{"event":{}}', {}, {})
        assert MondayNode.verify_webhook_signature(b"", {"x-foo": "bar"}, {"signing_secret": "s"})


class TestMondayErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_graphql_error_in_body(self, token_credentials):
        """monday returns HTTP 200 with an errors array — must be treated as error."""
        config = MondayNodeConfig(
            config=MondayGetBoardConfig(board_id="missing"), credentials=token_credentials
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(
            200, {"errors": [{"message": "Board not found"}]}
        )
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_http_error(self, token_credentials):
        config = MondayNodeConfig(
            config=MondayGetMeConfig(), credentials=token_credentials
        )
        node = create_monday_node(config)
        mock_client = create_mock_client(401, {"error_message": "Unauthorized"})
        with patch("nodes.monday_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 401

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = MondayNodeConfig(config=MondayGetMeConfig(), credentials=None)
        node = create_monday_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestMondayDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_board_options(self):
        with patch(
            "nodes.monday_node._monday_graphql",
            return_value={
                "status": "success",
                "data": {"boards": [{"id": "123", "name": "Tasks"}]},
            },
        ):
            result = await MondayNode.load_field_options(
                "board_id",
                credential_data={"api_token": "monday_test"},
            )
        assert "options" in result
        assert result["options"][0]["value"] == "123"
        assert result["options"][0]["label"] == "Tasks"
