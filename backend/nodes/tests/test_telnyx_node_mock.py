"""Exercise the public runner against Telnyx's documented request shapes."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import telnyx_node as node
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "telnyx_api_key", "api_key": "KEY-synthetic-unit-test"}
ID = "dd50eba1-a0c0-4563-9925-b25e842a7cb6"
CASES = [
    ("send_message", {"from_number": "+18445550001", "to": "+18445550001", "text": "Hello, World!"}, "POST", "/messages", {"from": "+18445550001", "to": "+18445550001", "text": "Hello, World!", "type": "SMS"}),
    ("get_message", {"id": ID}, "GET", "/messages/" + ID, None),
    ("cancel_message", {"id": ID}, "DELETE", "/messages/" + ID, None),
    ("list_messaging_profiles", {}, "GET", "/messaging_profiles", None),
    ("get_messaging_profile", {"id": ID}, "GET", "/messaging_profiles/" + ID, None),
    ("create_messaging_profile", {"name": "My name", "whitelisted_destinations": ["US"]}, "POST", "/messaging_profiles", {"name": "My name", "whitelisted_destinations": ["US"]}),
    ("update_messaging_profile", {"id": ID, "name": "Updated Profile for Messages"}, "PATCH", "/messaging_profiles/" + ID, {"name": "Updated Profile for Messages"}),
    ("delete_messaging_profile", {"id": ID}, "DELETE", "/messaging_profiles/" + ID, None),
    ("list_phone_numbers", {}, "GET", "/phone_numbers", None),
    ("get_phone_number", {"id": "1293384261075731499"}, "GET", "/phone_numbers/1293384261075731499", None),
    ("update_phone_number", {"id": "1293384261075731499", "customer_reference": "customer-reference", "tags": []}, "PATCH", "/phone_numbers/1293384261075731499", {"customer_reference": "customer-reference", "tags": []}),
    ("get_phone_number_messaging", {"id": ID}, "GET", "/phone_numbers/" + ID + "/messaging", None),
    ("update_phone_number_messaging", {"id": ID, "messaging_profile_id": ID}, "PATCH", "/phone_numbers/" + ID + "/messaging", {"messaging_profile_id": ID}),
    ("get_balance", {}, "GET", "/balance", None),
    ("list_number_orders", {}, "GET", "/number_orders", None),
    ("get_number_order", {"id": ID}, "GET", "/number_orders/" + ID, None),
    ("update_number_order", {"id": ID, "customer_reference": "MY REF 001"}, "PATCH", "/number_orders/" + ID, {"customer_reference": "MY REF 001"}),
]

async def run(op, config):
    return await run_node_operation(node_type="automation-telnyx", operation=op, arguments=config, credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001")

@pytest.fixture
def mock_http(monkeypatch):
    sent = []
    replies = []
    async def request(req):
        sent.append(req)
        return replies.pop(0)
    native = httpx.AsyncClient
    monkeypatch.setattr(node.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(request)))
    return sent, replies

@pytest.mark.parametrize("op,config,method,path,body", CASES)
async def test_request(op, config, method, path, body, mock_http):
    sent, replies = mock_http
    replies.append(httpx.Response(200, json={"data": {"id": ID, "v1_secret": "private"}}))
    result = await run(op, config)
    assert result["status"] == "success"
    assert result["data"] == {"id": ID}
    assert len(sent) == 1
    req = sent[0]
    assert req.method == method and req.url.path == "/v2" + path
    assert req.url.host == "api.telnyx.com"
    assert req.headers["Authorization"] == "Bearer " + AUTH["api_key"]
    assert (json.loads(req.content) if req.content else None) == body
    if op.startswith("list_"):
        assert dict(req.url.params) == {"page[number]": "1", "page[size]": "20"}

@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_rejection_and_no_retry(status, mock_http):
    sent, replies = mock_http
    replies.append(httpx.Response(status, json={"errors": [{"detail": "Rejected " + AUTH["api_key"]}]}))
    result = await run("list_phone_numbers", {})
    assert result["status"] == "error" and result["http_status"] == status
    assert AUTH["api_key"] not in json.dumps(result)
    assert len(sent) == 1

async def test_empty_delete(mock_http):
    _, replies = mock_http
    replies.append(httpx.Response(204))
    assert (await run("cancel_message", {"id": ID}))["acknowledged"]

@pytest.mark.parametrize("payload", [{}, {"errors": [{"detail": "bad"}]}, []])
async def test_unexpected_response(payload, mock_http):
    _, replies = mock_http
    replies.append(httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match="envelope"):
        await run("get_balance", {})

@pytest.mark.parametrize("identifier", ["../balance", "x/y", "https://example.com", "a?query=b"])
def test_path_injection(identifier):
    with pytest.raises(ValueError):
        node.GetPhoneNumber(id=identifier)

async def test_documented_mms_example(mock_http):
    documented = json.loads((Path(__file__).parent / "fixtures/telnyx/documented_requests.json").read_text())["examples"]["CreateMessageRequest"]
    sent, replies = mock_http
    replies.append(httpx.Response(200, json={"data": {"id": ID}}))
    config = {k: documented[k] for k in ("to", "text", "messaging_profile_id", "media_urls", "type")}
    config["from_number"] = documented["from"]
    await run("send_message", config)
    assert json.loads(sent[0].content) == {k: documented[k] for k in ("from", "to", "text", "messaging_profile_id", "media_urls", "type")}

async def test_partial_phone_number_errors_preserved(mock_http):
    _, replies = mock_http
    payload = {"data": [], "meta": {"page_number": 1}, "errors": [{"detail": "Messaging profile unavailable"}]}
    replies.append(httpx.Response(200, json=payload))
    result = await run("list_phone_numbers", {})
    assert result["data"] == [] and result["errors"] == payload["errors"]

async def test_documented_cancellation_response(mock_http):
    _, replies = mock_http
    body = json.loads((Path(__file__).parent / "fixtures/telnyx/cancelled_message.json").read_text())["body"]
    replies.append(httpx.Response(200, json=body))
    result = await run("cancel_message", {"id": ID})
    assert result["data"] == body
