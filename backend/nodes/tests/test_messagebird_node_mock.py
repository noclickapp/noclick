"""Exercise SMS requests and polling using MessageBird's own saved examples."""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.messagebird_node import MessageBirdNode, MessageBirdAPIKeyCredential

FIXTURES = Path(__file__).parent / "fixtures" / "messagebird"
KEY = "messagebird-test-key"


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())["body"]


def node(config):
    data = {"config": config, "credentials": {"credential_type": "messagebird_api_key", "api_key": KEY}}
    return MessageBirdNode("sms", "automation-messagebird", data, config=MessageBirdNode.parse_config(data))


@pytest.fixture
def transport(monkeypatch):
    requests = []
    response = {"body": fixture("created"), "status": 201}
    real = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        return httpx.Response(response["status"], json=response["body"] if response["status"] != 204 else None)

    monkeypatch.setattr("nodes.messagebird_node.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handle), **kw))
    return requests, response


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,kind", [
    ("send_sms", {}, "sms"),
    ("schedule_sms", {"scheduledDatetime": "2030-05-20T12:50:28Z"}, "sms"),
    ("send_flash_sms", {}, "flash"),
    ("send_binary_sms", {"udh": "050003340201", "body": "050003340201"}, "binary"),
])
async def test_send_requests(transport, operation, extra, kind):
    requests, _ = transport
    result = await node({"operation": operation, "originator": "YourName", "recipients": ["31612345678"],
                         "body": "This is a test message", **extra}).execute({})
    request = requests[0]
    assert request.method == "POST" and str(request.url) == "https://rest.messagebird.com/messages"
    assert request.headers["Authorization"] == "AccessKey " + KEY
    body = json.loads(request.content)
    assert body["type"] == kind and body["recipients"] == ["31612345678"]
    assert "operation" not in body and "udh" not in body
    if operation == "schedule_sms":
        assert body["scheduledDatetime"] == extra["scheduledDatetime"]
    if operation == "send_binary_sms":
        assert body["typeDetails"] == {"udh": "050003340201"}
    assert result["message"]["id"] == fixture("created")["id"]
    assert result["delivery_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,direction,extra", [
    ("list_messages", None, {}), ("list_received_messages", "mo", {}),
    ("list_sent_messages", "mt", {}), ("search_messages", None, {"searchterm": "YourName"}),
])
async def test_list_requests(transport, operation, direction, extra):
    requests, response = transport
    response.update(body=fixture("listed"), status=200)
    result = await node({"operation": operation, "from_time": "2022-05-20T12:50:28Z", **extra}).execute({})
    assert requests[0].method == "GET"
    assert requests[0].url.params.get("direction") == direction
    assert requests[0].url.params["from"] == "2022-05-20T12:50:28Z"
    assert "from_time" not in requests[0].url.params
    assert result["items"] == fixture("listed")["items"]
    assert result["next_offset"] is None


@pytest.mark.asyncio
async def test_get_and_delete(transport):
    requests, response = transport
    response.update(body=fixture("message"), status=200)
    result = await node({"operation": "get_message", "message_id": fixture("message")["id"]}).execute({})
    assert result["message"] == fixture("message")
    assert requests[-1].url.path == "/messages/" + fixture("message")["id"]
    response.update(body=None, status=204)
    result = await node({"operation": "delete_message", "message_id": "scheduled-id"}).execute({})
    assert requests[-1].method == "DELETE" and requests[-1].url.path == "/messages/scheduled-id"
    assert result == {"deleted_id": "scheduled-id", "deletion_acknowledged": True}


@pytest.mark.asyncio
async def test_errors_are_rejected_and_redacted(transport):
    requests, response = transport
    response.update(body={"errors": [{"description": "Not allowed " + KEY}]}, status=401)
    with pytest.raises(ValueError, match="Not allowed \\[redacted\\]"):
        await node({"operation": "list_messages"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_malformed_list_rejected(transport):
    _, response = transport
    response.update(body={"items": [{}], "totalCount": 1, "offset": 0}, status=200)
    with pytest.raises(ValueError, match="without an ID"):
        await node({"operation": "list_messages"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_message", "on_delivery_status_changed"])
async def test_poll_baselines_deduplicates_and_describes_documented_messages(transport, operation):
    requests, response = transport
    response.update(body=fixture("listed"), status=200)
    instance = node({"operation": operation})
    state = {}

    async def update(mutator, **kwargs):
        changed, result = mutator(state)
        if changed is not None:
            state.clear()
            state.update(changed)
        return result

    instance._update_node_state = update
    assert (await instance.execute({}))["new_event_count"] == 0
    assert "from" in requests[-1].url.params
    # A message (or delivery change) following the first baseline.
    response["body"] = copy.deepcopy(fixture("listed"))
    response["body"]["items"][0]["id"] = "new-message"
    output = await instance.execute({})
    assert output["new_event_count"] > 0
    event = MessageBirdNode.resolve_agent_event(output)
    assert "new-message" in event["text"]
    assert response["body"]["items"][0]["body"] in event["text"]
    assert (await instance.execute({}))["new_event_count"] == 0
    if operation == "on_delivery_status_changed":
        response["body"]["items"][0]["recipients"]["items"][0]["status"] = "expired"
        output = await instance.execute({})
        assert output["new_event_count"] == 1
        assert "expired" in MessageBirdNode.resolve_agent_event(output)["text"]


@pytest.mark.asyncio
async def test_poll_does_not_baseline_a_truncated_scan(monkeypatch):
    instance = node({"operation": "on_new_message"})
    instance._filter_unseen = AsyncMock()
    async def listing(key, params):
        return {"items": fixture("listed")["items"], "next_offset": params["offset"] + 100}
    monkeypatch.setattr(MessageBirdNode, "_list", staticmethod(listing))
    with pytest.raises(ValueError, match="2,000"):
        await instance.execute({})
    instance._filter_unseen.assert_not_awaited()


def test_credential_defaults_and_validation():
    assert MessageBirdAPIKeyCredential(api_key=KEY).credential_type == "messagebird_api_key"
    for bad in ["AccessKey secret", "https://example.com/key", "<token>"]:
        with pytest.raises(ValidationError):
            MessageBirdAPIKeyCredential(api_key=bad)
    for config in [
        {"operation": "get_message", "message_id": "../messages"},
        {"operation": "schedule_sms", "originator": "YourName", "recipients": ["31612345678"], "body": "test", "scheduledDatetime": "no timezone"},
    ]:
        with pytest.raises(Exception):
            node(config)
