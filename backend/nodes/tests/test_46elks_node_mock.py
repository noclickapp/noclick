"""Provider-published examples through the actual factory; no live account used."""
import base64
import importlib
import json
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes.core.registry import NodeFactory
from utils import ssrf

native = importlib.import_module("nodes.46elks_node")
FIXTURES = Path(__file__).parent / "fixtures" / "46elks"
CASES = json.loads((FIXTURES / "contract_examples.json").read_text())["cases"]
EVENTS = json.loads((FIXTURES / "events.json").read_text())
CREDENTIAL = {
    "credential_type": native.FAMILY,
    "api_username": "synthetic-user",
    "api_password": "synthetic-password",
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        status, body = replies.pop(0)
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    guarded = ssrf.guarded_async_client
    monkeypatch.setattr(
        native,
        "guarded_async_client",
        lambda **kwargs: guarded(**kwargs, transport=httpx.MockTransport(send)),
    )
    return requests, replies


def node(config):
    return NodeFactory.create_node(
        node_id="46elks-test",
        node_type="automation-46elks",
        node_data={"config": config, "credentials": CREDENTIAL},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(CASES))
async def test_all_published_contract_examples(transport, operation):
    requests, replies = transport
    case = CASES[operation]
    replies.append((200, case["body"]))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    request = requests[0]
    assert request.url.host == "api.46elks.com"
    assert (
        request.headers["authorization"]
        == "Basic " + base64.b64encode(b"synthetic-user:synthetic-password").decode()
    )
    assert "synthetic" not in str(request.url)
    spec = native.OPERATIONS[operation]
    assert request.method == spec["method"]
    assert request.url.path == "/a1" + spec["path"].replace(
        "{id}", str(case["config"].get("id", ""))
    )
    if spec["method"] == "POST":
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        body = parse_qs(request.content.decode())
        for key in spec["body"]:
            if key in case["config"]:
                assert body[key] == [str(case["config"][key])]
    assert "secret" not in result["data"]
    if isinstance(result["data"].get("data"), list):
        assert all("secret" not in row for row in result["data"]["data"])


@pytest.mark.asyncio
async def test_history_dates_are_query_parameters(transport):
    requests, replies = transport
    replies.append((200, {"data": []}))
    await node(
        {
            "operation": "list_sms",
            "start": "2016-01-01T00:00:00.000",
            "end": "2015-01-01T00:00:00.000",
        }
    ).execute({})
    assert dict(requests[0].url.params) == {
        "start": "2016-01-01T00:00:00.000",
        "end": "2015-01-01T00:00:00.000",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,field", [("on_incoming_sms", "sms_url"), ("on_incoming_mms", "mms_url")]
)
async def test_register_deliver_agent_and_unregister(transport, operation, field):
    requests, replies = transport
    url = "https://example.hooks.example.test/message"
    config = {
        "operation": operation,
        "number_id": "n57c8f48af76bf986a14f251b35389e8b",
        "webhook_url": url,
    }
    replies.append((200, {"id": config["number_id"], field: url}))
    extra = await native.Elks46Node._register_external_webhook(
        webhook_url=url, credential=CREDENTIAL, config=config, node_id="test"
    )
    assert extra["external_webhook_id"] == config["number_id"]
    assert parse_qs(requests[0].content.decode()) == {
        field: [url],
        **({"sms_replies": ["no"]} if field == "sms_url" else {}),
    }
    event = EVENTS["incoming_mms" if field == "mms_url" else "incoming_sms"]["body"]
    assert native.Elks46Node.verify_webhook_signature(b"", {}, config)
    assert native.Elks46Node.filter_trigger_payload(event, config)
    output = native.Elks46Node.resolve_trigger_payload(event, config)
    turn = native.Elks46Node.resolve_agent_event(output)
    assert event["from"] in turn["text"] and event["to"] in turn["text"]
    assert event["message"] in turn["text"] and event["id"] in turn["text"]
    assert turn["conversation_key"] == event["to"] + ":" + event["from"]
    if field == "mms_url":
        assert event["image"] in turn["text"]
    replies.extend(
        [
            (200, {"id": config["number_id"], field: url}),
            (200, {"id": config["number_id"]}),
        ]
    )
    await native.Elks46Node._unregister_external_webhook(
        credential=CREDENTIAL, config={**config, **extra}, node_id="test"
    )
    assert parse_qs(requests[-1].content.decode()) == {field: ["none"]}
    replies.append(
        (
            200,
            {"id": config["number_id"], field: "https://someone-else.example/callback"},
        )
    )
    await native.Elks46Node._unregister_external_webhook(
        credential=CREDENTIAL, config={**config, **extra}, node_id="test"
    )
    assert requests[-1].method == "GET"  # preserve a replacement callback
    assert (await node(config).execute({}))["status"] == "no_event"
    assert not native.Elks46Node.filter_trigger_payload(
        {**event, "direction": "outgoing"}, config
    )


@pytest.mark.asyncio
async def test_account_rejection_is_verbatim_and_redacts_secrets(transport):
    requests, replies = transport
    replies.append((401, "Permission denied synthetic-password"))
    with pytest.raises(
        ValueError, match="46elks API 401: Permission denied \\[redacted\\]"
    ):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.parametrize("bad", ["../SMS", "n/id", "n?query=1"])
def test_resource_id_cannot_change_route(bad):
    with pytest.raises(ValidationError):
        native.Elks46GetNumberConfig(id=bad)


@pytest.mark.parametrize("operation", ["update_number", "update_subaccount"])
def test_empty_updates_refused(operation):
    with pytest.raises(ValidationError):
        native.Elks46NodeConfig(config={"operation": operation, "id": "n123"})


@pytest.mark.asyncio
async def test_number_choices_and_manual_credential_default(transport):
    requests, replies = transport
    replies.append((200, CASES["list_numbers"]["body"]))
    options = await native.Elks46Node.load_field_options("number_id", CREDENTIAL)
    assert options and options[0]["label"].startswith("+")
    data = native.Elks46Credential(
        api_username="synthetic-user", api_password="synthetic-password"
    ).model_dump()
    assert data["credential_type"] == native.FAMILY
    assert native.Elks46Node.connection_evidence.operation == "get_account"
