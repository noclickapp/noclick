"""Exercise the real node factory with published Streak response examples."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import streak_node as streak
from nodes.core.registry import NodeFactory
from utils import ssrf

FIXTURES = Path(__file__).parent / "fixtures" / "streak"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
CASES = json.loads((FIXTURES / "cases.json").read_text())
AUTH = {"credential_type": "streak_api_key", "api_key": "streak-fixture-key"}


def node(config, credential=AUTH):
    return NodeFactory.create_node(
        node_id="streak-test",
        node_type="automation-streak",
        node_data={"config": config, "credentials": credential},
    )


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        streak,
        "guarded_async_client",
        lambda **kw: native(**kw, transport=httpx.MockTransport(send)),
    )
    return requests, replies


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(CASES))
async def test_published_examples_and_exact_wire_contract(wire, operation):
    requests, replies = wire
    replies.append((200, RESPONSES[operation]))
    result = await node(CASES[operation]).execute({})
    assert result == {
        "status": "success",
        "operation": operation,
        "data": RESPONSES[operation],
    }
    assert len(requests) == 1 and not replies
    request = requests[0]
    method, template = streak.ROUTES[operation]
    config = CASES[operation]
    for key, value in config.items():
        if key != "operation":
            template = template.replace("{" + key + "}", str(value))
    assert str(request.url) == streak.BASE_URL + template
    assert request.method == method
    assert request.headers["Authorization"] == "Basic c3RyZWFrLWZpeHR1cmUta2V5Og=="
    assert AUTH["api_key"] not in str(request.url)
    if method == "POST":
        expected = {
            k: v
            for k, v in config.items()
            if k != "operation" and not k.endswith("Key")
        }
        if operation == "create_task":
            expected["key"] = config["boxKey"]
        assert json.loads(request.content) == expected
        assert request.headers["Content-Type"] == "application/json"
    else:
        assert request.content == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 429, 500])
async def test_http_failure_is_not_retried_or_followed(wire, code):
    requests, replies = wire
    replies.append((code, {"error": "Rejected"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node(CASES["create_contact"]).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [{"success": False}, {"error": "No access"}, {"errors": ["Invalid"]}, "bad"]
)
async def test_error_envelope_is_not_success(wire, body):
    wire[1].append((200, body))
    with pytest.raises(ValueError):
        await node(CASES["list_teams"]).execute({})


@pytest.mark.parametrize(
    "value", ["bad:key", "bad\nkey", "https://example.com/key", "ＢＡＤ"]
)
def test_bad_key_rejected(value):
    with pytest.raises(ValidationError):
        streak.StreakAPIKeyCredential(api_key=value)


def test_manual_credential_default_and_trim():
    credential = streak.StreakAPIKeyCredential(api_key=" streak-fixture-key \n")
    assert credential.credential_type == "streak_api_key"
    assert credential.api_key == "streak-fixture-key"


@pytest.mark.parametrize("key", ["../other", "x?y=z", "x/y", "x#frag"])
def test_resource_key_cannot_change_route(key):
    with pytest.raises(ValidationError):
        streak.GetContact(contactKey=key)


@pytest.mark.asyncio
async def test_partial_update_preserves_omitted_fields_and_empty_lists(wire):
    wire[1].append((200, RESPONSES["update_contact"]))
    await node(
        {"operation": "update_contact", "contactKey": "contact", "emailAddresses": []}
    ).execute({})
    assert json.loads(wire[0][0].content) == {"emailAddresses": []}


@pytest.mark.asyncio
async def test_box_assignees_are_encoded_string_and_task_assignees_are_array(wire):
    wire[1].extend([(200, RESPONSES["create_box"]), (200, RESPONSES["create_task"])])
    encoded = '[{"email":"ginny@weasley.com"}]'
    await node(
        {
            "operation": "create_box",
            "pipelineKey": "pipeline",
            "name": "Deal",
            "assignedToSharingEntries": encoded,
        }
    ).execute({})
    await node(
        {
            "operation": "create_task",
            "boxKey": "box",
            "text": "Follow up",
            "assignedToSharingEntries": [{"email": "ginny@weasley.com"}],
        }
    ).execute({})
    assert json.loads(wire[0][0].content)["assignedToSharingEntries"] == encoded
    assert json.loads(wire[0][1].content)["assignedToSharingEntries"] == [
        {"email": "ginny@weasley.com"}
    ]
    assert json.loads(wire[0][1].content)["key"] == "box"


def test_no_empty_updates():
    with pytest.raises(ValidationError):
        streak.UpdateTask(taskKey="task")
