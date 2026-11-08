"""Native factory tests with synthetic HTTP; expectations transcribed from Blooio v4."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import blooio_node as native
from nodes.core.registry import NodeFactory

TOKEN = "bl_live_synthetic_fixture_only"
AUTH = {"credential_type": "blooio_api_key", "api_key": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/blooio/requests.json").read_text())["cases"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        assert request.url.host == "api.blooio.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        status, body = replies.pop(0)
        if isinstance(status, Exception):
            raise status
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests, replies


def node(config):
    return NodeFactory.create_node(node_id="blooio-fixture", node_type="automation-blooio",
        node_data={"config": config, "credentials": AUTH})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,params,body", CASES)
async def test_every_operation_wire_contract(transport, operation, config, method, path, params, body):
    requests, replies = transport
    sending = operation in {"send_message", "send_message_to_chat"}
    top_level = sending or operation == "create_chat"
    examples = json.loads((Path(__file__).parent / "fixtures/blooio/responses.json").read_text())
    reply = examples["POST /messages" if sending else "POST /chats"]["body"] if top_level else {"data": {"id": "fixture"}}
    replies.append((201 if sending else 200, reply))
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method
    assert request.url.raw_path.decode().split("?")[0] == "/v4" + path
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body
    if config.get("idempotency_key"):
        assert request.headers["Idempotency-Key"] == config["idempotency_key"]
    assert result["data"] == (reply if top_level else reply["data"])


@pytest.mark.asyncio
async def test_cursor_and_empty_page_are_preserved(transport):
    requests, replies = transport
    replies.extend([(200, {"data": [{"id": "ct_1", "name": "Alice"}], "has_more": True, "next_cursor": "opaque-next"}),
                    (200, {"data": [], "has_more": False, "next_cursor": None})])
    first = await node({"operation": "list_contacts"}).execute({})
    second = await node({"operation": "list_contacts", "cursor": first["next_cursor"]}).execute({})
    assert first["has_more"] is True and second["data"] == [] and second["has_more"] is False
    assert requests[1].url.params["cursor"] == "opaque-next"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": "ApiError", "message": "Unauthorized", "status": 401}),
    (403, {"error": {"code": "forbidden", "message": "Permission denied"}}),
    (429, {"error": {"code": "rate_limited", "message": "Too many requests"}}),
    (302, {"data": {}}), (500, {"error": {"message": TOKEN}}),
    (200, {"error": {"message": "Rejected"}}), (200, {}), (200, [])])
async def test_errors_and_redirects_are_never_success(transport, status, body):
    requests, replies = transport
    replies.append((status, body))
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)
    assert len(requests) == 1
    if status == 401:
        assert result["error"] == "Unauthorized"


@pytest.mark.asyncio
async def test_created_but_failed_message_is_an_error(transport):
    _, replies = transport
    replies.append((201, {"id": "msg_failed", "status": "failed", "error": {"message": "Recipient unavailable"}}))
    result = await node({"operation": "send_message", "to": "+15551234567", "text": "Hello"}).execute({})
    assert result["status"] == "error" and result["error"] == "Recipient unavailable"


@pytest.mark.asyncio
async def test_non_json_and_network_errors(transport, monkeypatch):
    _, replies = transport
    replies.append((200, b"not-json"))
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"
    replies.append((httpx.ConnectError("connection failed " + TOKEN), None))
    assert TOKEN not in str(await node({"operation": "get_account"}).execute({}))


@pytest.mark.parametrize("config", [{"operation": "create_chat"}, {"operation": "send_message", "to": "+15551234567"},
    {"operation": "list_chats", "limit": 201}, {"operation": "list_chats", "limit": 0},
    {"operation": "get_channel_health", "channel": "support", "days": 31},
    {"operation": "update_chat", "chat_id": "chat_1", "state": "invalid"},
    {"operation": "add_contact_tags", "contact_id": "ct_1", "tags": []},
    {"operation": "send_message", "to": "x", "text": "Hello", "unsupported": "ignored?"}])
def test_invalid_config_refused(config):
    with pytest.raises(ValueError):
        native.BlooioNode.parse_config({"config": config, "credentials": AUTH})


def test_secret_input_errors_hidden_and_paste_normalized():
    assert native.BlooioApiKeyCredential(api_key="  " + TOKEN + "  ").api_key == TOKEN
    with pytest.raises(ValidationError) as exc:
        native.BlooioApiKeyCredential(api_key="Bearer " + TOKEN)
    assert TOKEN not in str(exc.value)
