"""Requests and deliveries checked against Businessmap's published examples."""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.businessmap_node import BusinessmapAPIKeyCredential, BusinessmapNode, BusinessmapNodeConfig

FIXTURES = Path(__file__).parent / "fixtures" / "businessmap"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
EVENTS = json.loads((FIXTURES / "events.json").read_text())
CREDENTIAL = {"credential_type": "businessmap_api_key", "api_key": "valid123key", "account_url": "https://demo.kanbanize.com"}


def node(config):
    return BusinessmapNode(node_id="test", node_type="automation-businessmap", node_data={},
        config=BusinessmapNodeConfig.model_validate({"config": config, "credentials": CREDENTIAL}), sio=Mock())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,method,path,template,body", [
    ("get_current_user", {}, "GET", "/me", "/me", None),
    ("list_boards", {}, "GET", "/boards", "/boards", None),
    ("get_board", {"board_id": 1}, "GET", "/boards/1", "/boards/{board_id}", None),
    ("list_workspaces", {}, "GET", "/workspaces", "/workspaces", None),
    ("list_users", {}, "GET", "/users", "/users", None),
    ("list_workflows", {"board_id": 1}, "GET", "/boards/1/workflows", "/boards/{board_id}/workflows", None),
    ("get_board_structure", {"board_id": 1}, "GET", "/boards/1/currentStructure", "/boards/{board_id}/currentStructure", None),
    ("list_cards", {"page": 2, "per_page": 10, "board_ids": "1,2"}, "GET", "/cards", "/cards", None),
    ("get_card", {"card_id": 2}, "GET", "/cards/2", "/cards/{card_id}", None),
    ("create_card", {"title": "A task", "column_id": 1, "lane_id": 2}, "POST", "/cards", "/cards",
        {"title": "A task", "column_id": 1, "lane_id": 2}),
    ("update_card", {"card_id": 2, "column_id": 3, "is_archived": 1}, "PATCH", "/cards/2", "/cards/{card_id}",
        {"column_id": 3, "is_archived": 1}),
    ("delete_card", {"card_id": 2}, "DELETE", "/cards/2", "/cards/{card_id}", None),
    ("list_comments", {"card_id": 2}, "GET", "/cards/2/comments", "/cards/{card_id}/comments", None),
    ("add_comment", {"card_id": 2, "text": "Hello"}, "POST", "/cards/2/comments", "/cards/{card_id}/comments", {"text": "Hello"}),
    ("list_subtasks", {"card_id": 2}, "GET", "/cards/2/subtasks", "/cards/{card_id}/subtasks", None),
    ("create_subtask", {"card_id": 2, "description": "Do this"}, "POST", "/cards/2/subtasks", "/cards/{card_id}/subtasks", {"description": "Do this"}),
    ("update_subtask", {"card_id": 2, "subtask_id": 3, "is_finished": 1}, "PATCH", "/cards/2/subtasks/3", "/cards/{card_id}/subtasks/{subtask_id}", {"is_finished": 1}),
    ("delete_subtask", {"card_id": 2, "subtask_id": 3}, "DELETE", "/cards/2/subtasks/3", "/cards/{card_id}/subtasks/{subtask_id}", None),
    ("list_tags", {}, "GET", "/tags", "/tags", None),
    ("log_time", {"card_id": 2, "time": 3600, "date": "2025-07-20"}, "POST", "/loggedTime", "/loggedTime", {"card_id": 2, "time": 3600, "date": "2025-07-20"}),
])
async def test_documented_requests(operation, values, method, path, template, body):
    example = RESPONSES[method + " " + template]
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, "https://demo.kanbanize.com/api/v2" + path).mock(
            return_value=httpx.Response(example["status"], json=example["body"]) if example["status"] != 204 else httpx.Response(204))
        result = await node({"operation": operation, **values}).execute({})
    request = route.calls[0].request
    assert request.headers["apikey"] == CREDENTIAL["api_key"]
    assert "authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == body
    if operation == "list_cards":
        assert dict(request.url.params) == {"page": "2", "per_page": "10", "board_ids": "1,2"}
    assert result == (example["body"] if example["status"] != 204 else {"deleted": True})


@pytest.mark.asyncio
async def test_registration_cleanup_and_evidence():
    example = RESPONSES["POST /webhooks"]["body"]
    with respx.mock(assert_all_called=True) as router:
        create = router.post("https://demo.kanbanize.com/api/v2/webhooks").respond(200, json=example)
        delete = router.delete("https://demo.kanbanize.com/api/v2/webhooks/22").respond(204)
        router.get("https://demo.kanbanize.com/api/v2/boards").respond(200, json=RESPONSES["GET /boards"]["body"])
        registration = await BusinessmapNode._register_external_webhook(webhook_url="https://workflow.hooks.example.test/hook", credential=CREDENTIAL,
            config={"operation": "on_card_created", "board_id": 1}, node_id="test")
        assert registration == {"external_webhook_id": "22", "signing_secret": "abcdefghij1234567890"}
        assert json.loads(create.calls[0].request.content) == {"url": "https://workflow.hooks.example.test/hook", "board_id": 1, "is_enabled": 1}
        await BusinessmapNode._unregister_external_webhook(credential=CREDENTIAL, config=registration, node_id="test")
        assert delete.called
        options = await BusinessmapNode.load_field_options("board_id", CREDENTIAL)
        assert options["options"] and options["next_page_token"] is None


@pytest.mark.parametrize("operation,event", [
    ("on_card_created", "Card created"), ("on_card_updated", "Card details changed"),
    ("on_comment_created", "Comment created"), ("on_subtask_created", "Subtask created"),
])
def test_documented_deliveries(operation, event):
    payload = EVENTS[event]["body"]
    config = {"operation": operation, "board_id": 1, "signing_secret": "sharedsecret"}
    assert BusinessmapNode.verify_webhook_signature(b"{}", {"X-Kanbanize-Secret": "sharedsecret"}, config)
    for headers in ({}, {"x-kanbanize-secret": "wrong"}, {"x-kanbanize-secret": ""}):
        assert not BusinessmapNode.verify_webhook_signature(b"{}", headers, config)
    assert not BusinessmapNode.verify_webhook_signature(b"{}", {"x-kanbanize-secret": "sharedsecret"}, {})
    output = BusinessmapNode.resolve_trigger_payload({**payload, "_webhook": {"headers": {"secret": "hidden"}}}, config)
    assert output == payload
    turn = BusinessmapNode.resolve_agent_event(output)
    assert event in turn["text"] and "user 3" in turn["text"] and "board 1, card 2" in turn["text"]
    assert not BusinessmapNode.filter_trigger_payload({**payload, "board_id": 2}, config)
    assert not BusinessmapNode.filter_trigger_payload({**payload, "event": "Board deleted"}, config)
    assert BusinessmapNode.filter_trigger_payload(payload, {**config, "board_id": "1"})


@pytest.mark.parametrize("url", ["https://evil.com", "https://demo.kanbanize.com.evil.com", "http://demo.kanbanize.com", "https://demo.kanbanize.com@evil.com", "https://demo.kanbanize.com/api/v2", "https://127.0.0.1"])
def test_credential_rejects_foreign_hosts(url):
    with pytest.raises(ValueError):
        BusinessmapAPIKeyCredential.model_validate({**CREDENTIAL, "account_url": url})


def test_manual_connect_and_invalid_input():
    assert BusinessmapAPIKeyCredential(account_url="https://demo.kanbanize.com/", api_key=" valid123key ").credential_type == "businessmap_api_key"
    selected = node({"operation": "get_board", "board_id": "1", "board_id__label": "My board",
                     "credentialIds": {"businessmap_api_key": "saved"}})
    assert selected.config.config.model_dump() == {"operation": "get_board", "board_id": 1}
    for config in ({"operation": "create_card", "title": "missing location"}, {"operation": "update_card", "card_id": 2},
                   {"operation": "add_comment", "card_id": 2, "text": ""}, {"operation": "get_card", "card_id": -1},
                   {"operation": "update_card", "card_id": 2, "deadline": "2025-07-20T12:00:00"}):
        with pytest.raises(ValidationError):
            node(config)


@pytest.mark.asyncio
async def test_provider_rejection_is_visible_and_secret_is_redacted():
    with respx.mock:
        respx.get("https://demo.kanbanize.com/api/v2/me").respond(401, json={"error": {"message": "Invalid API key: valid123key"}})
        with pytest.raises(ValueError, match=r"HTTP 401: Invalid API key: \[redacted\]"):
            await node({"operation": "get_current_user"}).execute({})
