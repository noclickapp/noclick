"""
Mock tests for the Trello REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Search, Members (me, member boards, member cards)
- Boards: get, create, update, delete, lists, cards, labels, members, actions,
  add/remove member
- Lists: create, update, get cards, archive, move all cards
- Cards: get, create, update, delete, comment, attachment, add/remove member,
  add/remove label, get actions, get checklists
- Checklists: create, add item, update item, delete checklist, delete item
- Labels: create, update, delete
- Trigger: on_board_change / on_card_change passthrough, webhook registration/
  deregistration, signature verification, event-type filtering
- Error handling: API errors, missing credentials
- Dynamic options: board dropdown (new signature)
"""

import base64
import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.trello_node import (
    TrelloNode,
    TrelloNodeConfig,
    TrelloApiKeyCredential,
    TrelloSearchConfig,
    TrelloGetMeConfig,
    TrelloGetMemberBoardsConfig,
    TrelloGetMemberCardsConfig,
    TrelloGetBoardConfig,
    TrelloCreateBoardConfig,
    TrelloUpdateBoardConfig,
    TrelloDeleteBoardConfig,
    TrelloGetBoardListsConfig,
    TrelloGetBoardCardsConfig,
    TrelloGetBoardLabelsConfig,
    TrelloGetBoardMembersConfig,
    TrelloGetBoardActionsConfig,
    TrelloAddMemberToBoardConfig,
    TrelloRemoveMemberFromBoardConfig,
    TrelloCreateListConfig,
    TrelloUpdateListConfig,
    TrelloGetListCardsConfig,
    TrelloArchiveListConfig,
    TrelloMoveAllCardsConfig,
    TrelloGetCardConfig,
    TrelloCreateCardConfig,
    TrelloUpdateCardConfig,
    TrelloDeleteCardConfig,
    TrelloAddCommentConfig,
    TrelloAddAttachmentConfig,
    TrelloAddMemberConfig,
    TrelloRemoveMemberConfig,
    TrelloAddLabelConfig,
    TrelloRemoveLabelConfig,
    TrelloGetCardActionsConfig,
    TrelloGetCardChecklistsConfig,
    TrelloCreateChecklistConfig,
    TrelloAddChecklistItemConfig,
    TrelloUpdateChecklistItemConfig,
    TrelloDeleteChecklistConfig,
    TrelloDeleteChecklistItemConfig,
    TrelloCreateLabelConfig,
    TrelloUpdateLabelConfig,
    TrelloDeleteLabelConfig,
    TrelloBoardChangeTriggerConfig,
    TrelloCardChangeTriggerConfig,
    TRELLO_BOARD_EVENTS,
    TRELLO_CARD_EVENTS,
)


@pytest.fixture
def credentials():
    return TrelloApiKeyCredential(
        api_key="trello_key_123", api_token="trello_token_abc", api_secret="app_secret_xyz"
    )


def create_trello_node(config):
    return TrelloNode(
        node_id="test-trello-node",
        node_type="automation-trello",
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
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.trello_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


class TestTrelloSearchMembersMock:
    @pytest.mark.asyncio
    async def test_search(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(config=TrelloSearchConfig(query="bug"), credentials=credentials)
        )
        result = await _run(node, 200, {"cards": [{"id": "c1"}]})
        assert result["status"] == "success"
        assert result["action"] == "search"
        assert result["data"]["cards"][0]["id"] == "c1"

    @pytest.mark.asyncio
    async def test_get_me(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(config=TrelloGetMeConfig(), credentials=credentials)
        )
        result = await _run(node, 200, {"id": "m1", "username": "ada"})
        assert result["status"] == "success"
        assert result["action"] == "get_me"
        assert result["data"]["username"] == "ada"

    @pytest.mark.asyncio
    async def test_get_member_boards(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloGetMemberBoardsConfig(member_id="me"), credentials=credentials
            )
        )
        result = await _run(node, 200, [{"id": "b1", "name": "Roadmap"}])
        assert result["status"] == "success"
        assert result["action"] == "get_member_boards"
        assert result["data"][0]["name"] == "Roadmap"

    @pytest.mark.asyncio
    async def test_get_member_cards(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloGetMemberCardsConfig(member_id="me"), credentials=credentials
            )
        )
        result = await _run(node, 200, [{"id": "c1", "name": "Fix bug"}])
        assert result["status"] == "success"
        assert result["action"] == "get_member_cards"
        assert result["data"][0]["id"] == "c1"


class TestTrelloBoardsMock:
    @pytest.mark.asyncio
    async def test_get_board(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(config=TrelloGetBoardConfig(board_id="b1"), credentials=credentials)
        )
        result = await _run(node, 200, {"id": "b1", "name": "Roadmap"})
        assert result["status"] == "success"
        assert result["action"] == "get_board"
        assert result["data"]["id"] == "b1"

    @pytest.mark.asyncio
    async def test_create_board(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(config=TrelloCreateBoardConfig(name="New"), credentials=credentials)
        )
        result = await _run(node, 200, {"id": "b2", "name": "New"})
        assert result["status"] == "success"
        assert result["action"] == "create_board"
        assert result["data"]["name"] == "New"

    @pytest.mark.asyncio
    async def test_update_board(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloUpdateBoardConfig(board_id="b1", name="Renamed"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "b1", "name": "Renamed"})
        assert result["status"] == "success"
        assert result["action"] == "update_board"

    @pytest.mark.asyncio
    async def test_delete_board(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(config=TrelloDeleteBoardConfig(board_id="b1"), credentials=credentials)
        )
        result = await _run(node, 200, {"_value": None})
        assert result["status"] == "success"
        assert result["action"] == "delete_board"

    @pytest.mark.asyncio
    async def test_get_board_lists(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloGetBoardListsConfig(board_id="b1"), credentials=credentials
            )
        )
        result = await _run(node, 200, [{"id": "l1", "name": "To Do"}])
        assert result["status"] == "success"
        assert result["action"] == "get_board_lists"

    @pytest.mark.asyncio
    async def test_get_board_cards(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloGetBoardCardsConfig(board_id="b1"), credentials=credentials
            )
        )
        result = await _run(node, 200, [{"id": "c1"}])
        assert result["status"] == "success"
        assert result["action"] == "get_board_cards"

    @pytest.mark.asyncio
    async def test_get_board_labels(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloGetBoardLabelsConfig(board_id="b1"), credentials=credentials
            )
        )
        result = await _run(node, 200, [{"id": "lab1", "name": "Bug"}])
        assert result["status"] == "success"
        assert result["action"] == "get_board_labels"

    @pytest.mark.asyncio
    async def test_get_board_members(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloGetBoardMembersConfig(board_id="b1"), credentials=credentials
            )
        )
        result = await _run(node, 200, [{"id": "m1"}])
        assert result["status"] == "success"
        assert result["action"] == "get_board_members"

    @pytest.mark.asyncio
    async def test_get_board_actions(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloGetBoardActionsConfig(board_id="b1"), credentials=credentials
            )
        )
        result = await _run(node, 200, [{"id": "act1", "type": "createCard"}])
        assert result["status"] == "success"
        assert result["action"] == "get_board_actions"
        assert result["data"][0]["type"] == "createCard"

    @pytest.mark.asyncio
    async def test_add_member_to_board(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloAddMemberToBoardConfig(board_id="b1", id_member="m1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "b1", "memberships": [{"idMember": "m1"}]})
        assert result["status"] == "success"
        assert result["action"] == "add_member_to_board"

    @pytest.mark.asyncio
    async def test_remove_member_from_board(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloRemoveMemberFromBoardConfig(board_id="b1", id_member="m1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "b1", "memberships": []})
        assert result["status"] == "success"
        assert result["action"] == "remove_member_from_board"


class TestTrelloListsMock:
    @pytest.mark.asyncio
    async def test_create_list(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloCreateListConfig(name="Backlog", board_id="b1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "l9", "name": "Backlog"})
        assert result["status"] == "success"
        assert result["action"] == "create_list"
        assert result["data"]["name"] == "Backlog"

    @pytest.mark.asyncio
    async def test_update_list(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloUpdateListConfig(list_id="l1", name="In Progress"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "l1", "name": "In Progress"})
        assert result["status"] == "success"
        assert result["action"] == "update_list"
        assert result["data"]["name"] == "In Progress"

    @pytest.mark.asyncio
    async def test_get_list_cards(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(config=TrelloGetListCardsConfig(list_id="l1"), credentials=credentials)
        )
        result = await _run(node, 200, [{"id": "c1"}])
        assert result["status"] == "success"
        assert result["action"] == "get_list_cards"

    @pytest.mark.asyncio
    async def test_archive_list(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloArchiveListConfig(list_id="l1", value="true"), credentials=credentials
            )
        )
        result = await _run(node, 200, {"id": "l1", "closed": True})
        assert result["status"] == "success"
        assert result["action"] == "archive_list"

    @pytest.mark.asyncio
    async def test_move_all_cards(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloMoveAllCardsConfig(list_id="l1", id_board="b1", id_list="l2"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, [{"id": "c1"}])
        assert result["status"] == "success"
        assert result["action"] == "move_all_cards"


class TestTrelloCardsMock:
    @pytest.mark.asyncio
    async def test_get_card(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(config=TrelloGetCardConfig(card_id="c1"), credentials=credentials)
        )
        result = await _run(node, 200, {"id": "c1", "name": "Fix bug"})
        assert result["status"] == "success"
        assert result["action"] == "get_card"
        assert result["data"]["name"] == "Fix bug"

    @pytest.mark.asyncio
    async def test_create_card(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloCreateCardConfig(
                    id_list="l1", name="New card", id_members="m1,m2", id_labels="lab1"
                ),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "c9", "name": "New card"})
        assert result["status"] == "success"
        assert result["action"] == "create_card"
        assert result["data"]["id"] == "c9"

    @pytest.mark.asyncio
    async def test_update_card(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloUpdateCardConfig(card_id="c1", name="Renamed", id_list="l2"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "c1", "name": "Renamed"})
        assert result["status"] == "success"
        assert result["action"] == "update_card"

    @pytest.mark.asyncio
    async def test_delete_card(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(config=TrelloDeleteCardConfig(card_id="c1"), credentials=credentials)
        )
        result = await _run(node, 200, {"_value": None})
        assert result["status"] == "success"
        assert result["action"] == "delete_card"

    @pytest.mark.asyncio
    async def test_add_comment(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloAddCommentConfig(card_id="c1", text="Looks good"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "act1"})
        assert result["status"] == "success"
        assert result["action"] == "add_comment"

    @pytest.mark.asyncio
    async def test_add_attachment(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloAddAttachmentConfig(card_id="c1", url="https://x.com/f.png"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "att1"})
        assert result["status"] == "success"
        assert result["action"] == "add_attachment"

    @pytest.mark.asyncio
    async def test_add_member(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloAddMemberConfig(card_id="c1", value="m1"), credentials=credentials
            )
        )
        result = await _run(node, 200, [{"id": "m1"}])
        assert result["status"] == "success"
        assert result["action"] == "add_member"

    @pytest.mark.asyncio
    async def test_remove_member(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloRemoveMemberConfig(card_id="c1", id_member="m1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"_value": None})
        assert result["status"] == "success"
        assert result["action"] == "remove_member"

    @pytest.mark.asyncio
    async def test_add_label(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloAddLabelConfig(card_id="c1", value="lab1"), credentials=credentials
            )
        )
        result = await _run(node, 200, [{"id": "lab1"}])
        assert result["status"] == "success"
        assert result["action"] == "add_label"

    @pytest.mark.asyncio
    async def test_remove_label(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloRemoveLabelConfig(card_id="c1", id_label="lab1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"_value": None})
        assert result["status"] == "success"
        assert result["action"] == "remove_label"

    @pytest.mark.asyncio
    async def test_get_card_actions(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloGetCardActionsConfig(card_id="c1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, [{"id": "act1", "type": "commentCard"}])
        assert result["status"] == "success"
        assert result["action"] == "get_card_actions"
        assert result["data"][0]["type"] == "commentCard"

    @pytest.mark.asyncio
    async def test_get_card_checklists(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloGetCardChecklistsConfig(card_id="c1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, [{"id": "cl1", "name": "Steps"}])
        assert result["status"] == "success"
        assert result["action"] == "get_card_checklists"
        assert result["data"][0]["id"] == "cl1"


class TestTrelloChecklistsMock:
    @pytest.mark.asyncio
    async def test_create_checklist(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloCreateChecklistConfig(card_id="c1", name="Steps"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "cl1", "name": "Steps"})
        assert result["status"] == "success"
        assert result["action"] == "create_checklist"

    @pytest.mark.asyncio
    async def test_add_checklist_item(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloAddChecklistItemConfig(checklist_id="cl1", name="First step"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "ci1", "name": "First step"})
        assert result["status"] == "success"
        assert result["action"] == "add_checklist_item"

    @pytest.mark.asyncio
    async def test_update_checklist_item(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloUpdateChecklistItemConfig(
                    card_id="c1", check_item_id="ci1", state="complete"
                ),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "ci1", "state": "complete"})
        assert result["status"] == "success"
        assert result["action"] == "update_checklist_item"
        assert result["data"]["state"] == "complete"

    @pytest.mark.asyncio
    async def test_delete_checklist(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloDeleteChecklistConfig(checklist_id="cl1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"_value": None})
        assert result["status"] == "success"
        assert result["action"] == "delete_checklist"

    @pytest.mark.asyncio
    async def test_delete_checklist_item(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloDeleteChecklistItemConfig(checklist_id="cl1", check_item_id="ci1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"_value": None})
        assert result["status"] == "success"
        assert result["action"] == "delete_checklist_item"


class TestTrelloLabelsMock:
    @pytest.mark.asyncio
    async def test_create_label(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloCreateLabelConfig(board_id="b1", name="Bug", color="red"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "lab9", "name": "Bug", "color": "red"})
        assert result["status"] == "success"
        assert result["action"] == "create_label"
        assert result["data"]["color"] == "red"

    @pytest.mark.asyncio
    async def test_update_label(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloUpdateLabelConfig(label_id="lab1", name="Feature", color="green"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"id": "lab1", "name": "Feature", "color": "green"})
        assert result["status"] == "success"
        assert result["action"] == "update_label"

    @pytest.mark.asyncio
    async def test_delete_label(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(
                config=TrelloDeleteLabelConfig(label_id="lab1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, {"_value": None})
        assert result["status"] == "success"
        assert result["action"] == "delete_label"


class TestTrelloTriggerMock:
    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.trello_node._trello_request",
            return_value={"status": "success", "data": {"id": "wh99"}},
        ) as mock_req:
            extra = await TrelloNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={
                    "api_key": "k",
                    "api_token": "t",
                    "api_secret": "app_secret_xyz",
                },
                config={"board_id": "b1", "event_types": "createCard"},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "wh99"
        assert extra["signing_secret"] == "app_secret_xyz"
        assert extra["callback_url"] == "https://abc.hooks.example.test"
        # Trello has no per-subscription event filter — registration subscribes
        # to the model (the chosen event is enforced in filter_trigger_payload),
        # so the create-webhook call carries idModel but no event param.
        _, kwargs = mock_req.call_args
        assert kwargs["params"]["idModel"] == "b1"
        assert "event_types" not in kwargs["params"]
        assert "events" not in kwargs["params"]

    @pytest.mark.asyncio
    async def test_register_external_webhook_requires_model(self):
        with pytest.raises(ValueError, match="board or card ID"):
            await TrelloNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "k", "api_token": "t"},
                config={},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.trello_node._trello_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await TrelloNode._unregister_external_webhook(
                credential={"api_key": "k", "api_token": "t"},
                config={"external_webhook_id": "wh99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_event_types_defaults_to_all(self):
        """Both triggers default to firing on any change ('*')."""
        assert TrelloBoardChangeTriggerConfig(board_id="b1").event_types == "*"
        assert TrelloCardChangeTriggerConfig(card_id="c1").event_types == "*"

    def test_filter_trigger_payload_wildcard_passes_all(self):
        """'*' accepts every action.type."""
        for action_type in ("createCard", "commentCard", "updateBoard"):
            payload = {"action": {"type": action_type}, "model": {"id": "b1"}}
            assert TrelloNode.filter_trigger_payload(payload, {"event_types": "*"})
        # Missing/empty selection is treated as wildcard too.
        assert TrelloNode.filter_trigger_payload(
            {"action": {"type": "createCard"}}, {}
        )

    def test_filter_trigger_payload_passes_selected_event(self):
        """A specific selection fires only on the matching action.type."""
        payload = {"action": {"type": "commentCard"}, "model": {"id": "c1"}}
        assert TrelloNode.filter_trigger_payload(
            payload, {"event_types": "commentCard"}
        )

    def test_filter_trigger_payload_skips_non_selected_event(self):
        """A non-matching action.type is skipped (returns False)."""
        payload = {"action": {"type": "updateCard"}, "model": {"id": "c1"}}
        assert not TrelloNode.filter_trigger_payload(
            payload, {"event_types": "commentCard"}
        )
        # No action.type at all -> skip when a specific event is selected.
        assert not TrelloNode.filter_trigger_payload(
            {"model": {"id": "c1"}}, {"event_types": "createCard"}
        )

    def test_verify_webhook_signature(self):
        secret = "app_secret_xyz"
        callback = "https://abc.hooks.example.test"
        body = b'{"action":{"type":"updateCard"}}'
        digest = hmac.new(secret.encode(), body + callback.encode(), hashlib.sha1).digest()
        good_sig = base64.b64encode(digest).decode()
        cfg = {"signing_secret": secret, "callback_url": callback}
        assert TrelloNode.verify_webhook_signature(body, {"x-trello-webhook": good_sig}, cfg)
        assert not TrelloNode.verify_webhook_signature(
            body, {"x-trello-webhook": "deadbeef"}, cfg
        )
        # no secret stored yet -> accept (signature verification not armed)
        assert TrelloNode.verify_webhook_signature(body, {}, {})


class TestTrelloBoardChangeTriggerMock:
    """Tests for the on_board_change trigger (board-scoped webhook)."""

    @pytest.mark.asyncio
    async def test_on_board_change_passthrough(self):
        """Board trigger passes the webhook payload + webhook_url as output."""
        config = TrelloNodeConfig(
            config=TrelloBoardChangeTriggerConfig(
                board_id="b1", webhook_url="https://abc.hooks.example.test"
            ),
            credentials=None,
        )
        node = create_trello_node(config)
        payload = {"action": {"type": "createCard"}, "model": {"id": "b1"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_board_change"
        assert result["data"]["action"]["type"] == "createCard"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    def test_board_trigger_defaults(self):
        """Board trigger defaults: event_types='*', no board_id required to construct but required by validation."""
        cfg = TrelloBoardChangeTriggerConfig(board_id="b1")
        assert cfg.event_types == "*"
        assert cfg.board_id == "b1"
        assert cfg.operation == "on_board_change"

    def test_board_trigger_event_list_complete(self):
        """Board events include both card-level and board-level events."""
        assert "createCard" in TRELLO_BOARD_EVENTS
        assert "updateBoard" in TRELLO_BOARD_EVENTS
        assert "createList" in TRELLO_BOARD_EVENTS
        assert "addMemberToBoard" in TRELLO_BOARD_EVENTS
        assert "*" in TRELLO_BOARD_EVENTS
        # Board events is a superset of card events (minus "*")
        card_events_no_wildcard = {e for e in TRELLO_CARD_EVENTS if e != "*"}
        board_events_set = set(TRELLO_BOARD_EVENTS)
        assert card_events_no_wildcard.issubset(board_events_set)

    @pytest.mark.asyncio
    async def test_board_register_uses_board_id(self):
        """_register_external_webhook uses board_id for on_board_change."""
        with patch(
            "nodes.trello_node._trello_request",
            return_value={"status": "success", "data": {"id": "wh-board"}},
        ) as mock_req:
            extra = await TrelloNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "k", "api_token": "t", "api_secret": "s"},
                config={"operation": "on_board_change", "board_id": "b1", "event_types": "createCard"},
                node_id="node-1",
            )
        _, kwargs = mock_req.call_args
        assert kwargs["params"]["idModel"] == "b1"
        assert extra["external_webhook_id"] == "wh-board"
        assert extra["signing_secret"] == "s"

    def test_board_filter_specific_event(self):
        """on_board_change filter passes matching board events."""
        assert TrelloNode.filter_trigger_payload(
            {"action": {"type": "createCard"}},
            {"operation": "on_board_change", "event_types": "createCard"},
        )
        assert not TrelloNode.filter_trigger_payload(
            {"action": {"type": "updateList"}},
            {"operation": "on_board_change", "event_types": "createCard"},
        )

    def test_board_filter_wildcard(self):
        """on_board_change with '*' passes all events."""
        for event in ["createCard", "updateBoard", "addMemberToBoard", "commentCard"]:
            assert TrelloNode.filter_trigger_payload(
                {"action": {"type": event}},
                {"operation": "on_board_change", "event_types": "*"},
            )

    def test_board_signature_verification(self):
        """verify_webhook_signature works identically for board trigger."""
        secret = "board_secret"
        callback = "https://abc.hooks.example.test/board"
        body = b'{"action":{"type":"createCard"}}'
        digest = hmac.new(secret.encode(), body + callback.encode(), hashlib.sha1).digest()
        sig = base64.b64encode(digest).decode()
        cfg = {
            "operation": "on_board_change",
            "signing_secret": secret,
            "callback_url": callback,
        }
        assert TrelloNode.verify_webhook_signature(body, {"x-trello-webhook": sig}, cfg)
        assert not TrelloNode.verify_webhook_signature(
            body, {"x-trello-webhook": "badsig"}, cfg
        )


class TestTrelloCardChangeTriggerMock:
    """Tests for the on_card_change trigger (card-scoped webhook)."""

    @pytest.mark.asyncio
    async def test_on_card_change_passthrough(self):
        """Card trigger passes the webhook payload + webhook_url as output."""
        config = TrelloNodeConfig(
            config=TrelloCardChangeTriggerConfig(
                card_id="c1", webhook_url="https://abc.hooks.example.test"
            ),
            credentials=None,
        )
        node = create_trello_node(config)
        payload = {"action": {"type": "commentCard", "data": {"text": "hello"}}, "model": {"id": "c1"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_card_change"
        assert result["data"]["action"]["type"] == "commentCard"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    def test_card_trigger_defaults(self):
        """Card trigger defaults: event_types='*'."""
        cfg = TrelloCardChangeTriggerConfig(card_id="c1")
        assert cfg.event_types == "*"
        assert cfg.card_id == "c1"
        assert cfg.operation == "on_card_change"

    def test_card_trigger_event_list(self):
        """Card events are a focused subset (no board/list events)."""
        assert "commentCard" in TRELLO_CARD_EVENTS
        assert "updateCard" in TRELLO_CARD_EVENTS
        assert "updateCheckItemStateOnCard" in TRELLO_CARD_EVENTS
        assert "*" in TRELLO_CARD_EVENTS
        # Board-only events must NOT appear in the card event list
        assert "createList" not in TRELLO_CARD_EVENTS
        assert "updateBoard" not in TRELLO_CARD_EVENTS
        assert "addMemberToBoard" not in TRELLO_CARD_EVENTS
        assert "createCard" not in TRELLO_CARD_EVENTS  # createCard only fires on board model

    @pytest.mark.asyncio
    async def test_card_register_uses_card_id(self):
        """_register_external_webhook uses card_id for on_card_change."""
        with patch(
            "nodes.trello_node._trello_request",
            return_value={"status": "success", "data": {"id": "wh-card"}},
        ) as mock_req:
            extra = await TrelloNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "k", "api_token": "t", "api_secret": "s"},
                config={"operation": "on_card_change", "card_id": "c1", "event_types": "commentCard"},
                node_id="node-1",
            )
        _, kwargs = mock_req.call_args
        assert kwargs["params"]["idModel"] == "c1"
        assert extra["external_webhook_id"] == "wh-card"

    def test_card_filter_specific_event(self):
        """on_card_change filter passes matching card events."""
        assert TrelloNode.filter_trigger_payload(
            {"action": {"type": "commentCard"}},
            {"operation": "on_card_change", "event_types": "commentCard"},
        )
        assert not TrelloNode.filter_trigger_payload(
            {"action": {"type": "updateCard"}},
            {"operation": "on_card_change", "event_types": "commentCard"},
        )

    def test_card_filter_wildcard(self):
        """on_card_change with '*' passes all card events."""
        for event in ["commentCard", "updateCard", "addMemberToCard", "updateCheckItemStateOnCard"]:
            assert TrelloNode.filter_trigger_payload(
                {"action": {"type": event}},
                {"operation": "on_card_change", "event_types": "*"},
            )

    def test_card_signature_verification(self):
        """verify_webhook_signature is identical for card trigger."""
        secret = "card_secret"
        callback = "https://abc.hooks.example.test/card"
        body = b'{"action":{"type":"commentCard"}}'
        digest = hmac.new(secret.encode(), body + callback.encode(), hashlib.sha1).digest()
        sig = base64.b64encode(digest).decode()
        cfg = {
            "operation": "on_card_change",
            "signing_secret": secret,
            "callback_url": callback,
        }
        assert TrelloNode.verify_webhook_signature(body, {"x-trello-webhook": sig}, cfg)

    @pytest.mark.asyncio
    async def test_register_card_webhook_no_id_fails(self):
        """on_card_change registration fails if card_id is missing."""
        with pytest.raises(ValueError, match="board or card ID"):
            await TrelloNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "k", "api_token": "t"},
                config={"operation": "on_card_change"},  # no card_id
                node_id="node-1",
            )

    def test_two_triggers_are_distinct_operations(self):
        """Both trigger types have distinct operation literals."""
        board_cfg = TrelloBoardChangeTriggerConfig(board_id="b1")
        card_cfg = TrelloCardChangeTriggerConfig(card_id="c1")
        assert board_cfg.operation == "on_board_change"
        assert card_cfg.operation == "on_card_change"

    def test_board_change_event_types_field_uses_board_events(self):
        """on_board_change enumerates board events (not card events)."""
        import json
        schema = TrelloBoardChangeTriggerConfig.model_json_schema()
        event_types_schema = schema["properties"]["event_types"]
        enum_vals = event_types_schema.get("enum", [])
        assert "updateBoard" in enum_vals
        assert "createList" in enum_vals

    def test_card_change_event_types_field_uses_card_events(self):
        """on_card_change enumerates card-only events (no board/list events)."""
        import json
        schema = TrelloCardChangeTriggerConfig.model_json_schema()
        event_types_schema = schema["properties"]["event_types"]
        enum_vals = event_types_schema.get("enum", [])
        assert "commentCard" in enum_vals
        assert "updateBoard" not in enum_vals
        assert "createList" not in enum_vals


class TestTrelloErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, credentials):
        node = create_trello_node(
            TrelloNodeConfig(config=TrelloGetCardConfig(card_id="missing"), credentials=credentials)
        )
        result = await _run(node, 404, {"message": "card not found"})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = TrelloNodeConfig(config=TrelloGetMeConfig(), credentials=None)
        node = create_trello_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestTrelloDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_board_options(self):
        with patch(
            "nodes.trello_node._trello_request",
            return_value={
                "status": "success",
                "data": [
                    {"id": "b1", "name": "Roadmap", "closed": False},
                    {"id": "b2", "name": "Archived", "closed": True},
                ],
            },
        ):
            result = await TrelloNode.load_field_options(
                "board_id",
                credential_data={"api_key": "k", "api_token": "t"},
            )
        assert "options" in result
        # closed board filtered out
        assert len(result["options"]) == 1
        assert result["options"][0]["value"] == "b1"
        assert result["options"][0]["label"] == "Roadmap"

    @pytest.mark.asyncio
    async def test_load_unknown_field_returns_empty(self):
        result = await TrelloNode.load_field_options(
            "unknown_field",
            credential_data={"api_key": "k", "api_token": "t"},
        )
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_load_board_options_no_credentials(self):
        result = await TrelloNode.load_field_options("board_id", credential_data=None)
        assert result == {"options": []}
