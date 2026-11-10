"""Test Zenzap's exact request signing and documented response handling.

Polling tests exercise baselines, new items, deduplication and malformed
responses without advancing state after an invalid read.
"""
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.zenzap_node import ZenzapNode, ZenzapNodeConfig

FIXTURES = json.loads((Path(__file__).parent / "fixtures/zenzap/responses.json").read_text())["responses"]
TOPIC = "550e8400-e29b-41d4-a716-446655440000"
MESSAGE = "660e8400-e29b-41d4-a716-446655440001"


def node(operation, **values):
    return ZenzapNode(node_id="zenzap-test", node_type="automation-zenzap", node_data={},
        config=ZenzapNodeConfig.model_validate({"config": {"operation": operation, **values},
            "credentials": {"api_key": "test-key", "api_secret": "test-secret"}}),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,method,path,body", [
    ("send_message", {"topic_id": TOPIC, "text": "Hello from my integration!"}, "POST", "/v2/messages", {"topicId": TOPIC, "text": "Hello from my integration!"}),
    ("edit_message", {"message_id": MESSAGE, "text": "Updated message content"}, "PATCH", f"/v2/messages/{MESSAGE}", {"text": "Updated message content"}),
    ("delete_message", {"message_id": MESSAGE}, "DELETE", f"/v2/messages/{MESSAGE}", None),
    ("add_reaction", {"message_id": MESSAGE, "reaction": "👍"}, "POST", f"/v2/messages/{MESSAGE}/reactions", {"reaction": "👍"}),
    ("add_topic_members", {"topic_id": TOPIC, "member_ids": [TOPIC]}, "POST", f"/v2/topics/{TOPIC}/members", {"memberIds": [TOPIC]}),
    ("remove_topic_members", {"topic_id": TOPIC, "member_ids": [TOPIC]}, "DELETE", f"/v2/topics/{TOPIC}/members", {"memberIds": [TOPIC]}),
    ("list_members", {"emails": "john@example.com,jane@example.com", "cursor": "opaque+/="}, "GET", "/v2/members", None),
    ("update_task", {"task_id": MESSAGE, "topic_id": TOPIC, "status": "Done", "due_date": 0, "unassign": True}, "PATCH", f"/v2/tasks/{MESSAGE}", {"topicId": TOPIC, "status": "Done", "dueDate": 0, "assignee": ""}),
    ("get_topic_by_external_id", {"external_id": "project/alpha?"}, "GET", "/v2/topics/external/project%2Falpha%3F", None),
])
async def test_signed_wire_requests(operation, values, method, path, body):
    response = FIXTURES.get(operation, {"status": 204, "body": None})
    with respx.mock(assert_all_called=True) as router:
        route = router.route(method=method, url__regex=r"https://api\.zenzap\.co/.*").mock(
            return_value=httpx.Response(response["status"], json=response["body"]) if response["body"] is not None else httpx.Response(204))
        result = await node(operation, **values).execute({})
    request = route.calls[0].request
    assert request.url.raw_path.split(b"?")[0].decode() == path
    signed = request.url.raw_path if method == "GET" else request.content
    expected = hmac.new(b"test-secret", request.headers["X-Timestamp"].encode() + b"." + signed, hashlib.sha256).hexdigest()
    assert request.headers["X-Signature"] == expected
    assert request.headers["Authorization"] == "Bearer test-key"
    assert (json.loads(request.content) if request.content else None) == body
    if operation == "list_members":
        assert request.url.params["emails"] == values["emails"]
        assert request.url.params["cursor"] == values["cursor"]
    assert result["data"] == (response["body"] or {})


@pytest.mark.parametrize("operation,values", [
    ("update_task", {"task_id": MESSAGE, "status": "Done"}),
    ("update_task", {"task_id": MESSAGE, "name": "A", "title": "B"}),
    ("update_task", {"task_id": MESSAGE}),
    ("update_topic", {"topic_id": TOPIC}),
    ("list_messages", {"topic_id": TOPIC, "before": 1, "after": 2}),
    ("add_topic_members", {"topic_id": TOPIC, "member_ids": [TOPIC] * 6}),
])
def test_reject_invalid_provider_inputs(operation, values):
    with pytest.raises(ValidationError):
        node(operation, **values)


def test_unassign_survives_runtime_config_normalization():
    parsed = ZenzapNode.parse_config({"config": {"operation": "update_task", "task_id": MESSAGE, "unassign": True}})
    assert parsed.config.unassign


def test_canvas_metadata_is_not_an_api_parameter():
    parsed = ZenzapNode.parse_config({"config": {"operation": "list_topics",
        "credentialIds": {"zenzap_api_key": "saved-credential"}, "goal": "List team chats"}})
    assert parsed.config.model_dump() == {"operation": "list_topics", "limit": 50, "cursor": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,key,listing,config", [
    ("on_new_topic", "topics", "list_topics", {}),
    ("on_new_message", "messages", "list_messages", {"topic_id": TOPIC}),
])
async def test_poll_baseline_new_items_and_dedup(operation, key, listing, config):
    instance = node(operation, **config)
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        replacement, result = mutator(state)
        if replacement is not None:
            state = replacement
        return result
    instance._update_node_state = update
    documented = FIXTURES[listing]["body"]
    original = documented
    new_row = {**original[key][0], "id": "550e8400-e29b-41d4-a716-446655440099"}
    newer = {**original, key: [new_row, *original[key]]}
    with respx.mock as router:
        router.get(url__regex=r"https://api\.zenzap\.co/v2/topics.*").mock(side_effect=[
            httpx.Response(200, json=original), httpx.Response(200, json=newer), httpx.Response(200, json=newer)])
        first = await instance.execute({})
        assert first[key] == []
        assert first["window_limit"] == 100
        assert first["has_older_items"] == documented["hasMore"]
        assert instance.trigger_produced_no_event(first)
        second = await instance.execute({})
        assert second[key] == [new_row]
        assert instance.trigger_emitted_event(second)
        event = ZenzapNode.resolve_agent_event(second)
        assert new_row["id"] in event["text"]
        if key == "messages":
            assert new_row["senderName"] in event["text"]
            assert new_row["text"] in event["text"]
            assert event["conversation_key"] == TOPIC
        assert (await instance.execute({}))[key] == []


@pytest.mark.asyncio
async def test_poll_invalid_response_does_not_advance_state():
    instance = node("on_new_topic")
    instance._update_node_state = Mock(side_effect=AssertionError("Must not advance partial listing"))
    with respx.mock:
        respx.get("https://api.zenzap.co/v2/topics").mock(return_value=httpx.Response(200, json={"topics": [{"name": "Missing ID"}]}))
        with pytest.raises(ValueError, match="invalid topics page"):
            await instance.execute({})


@pytest.mark.asyncio
async def test_provider_error_redacts_both_secrets():
    with respx.mock:
        respx.get("https://api.zenzap.co/v2/members/me").mock(return_value=httpx.Response(401, text="Invalid test-key and test-secret"))
        with pytest.raises(ValueError, match=r"HTTP 401: Invalid \[redacted\] and \[redacted\]"):
            await node("get_current_member").execute({})
