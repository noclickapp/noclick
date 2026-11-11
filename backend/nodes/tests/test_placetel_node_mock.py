"""Exercise native discovery and real HTTP serialization against provider-shaped fixtures."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import placetel_node as node
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "placetel_api_key", "api_key": "fixture-placetel-secret"}
ME = json.loads((Path(__file__).parent / "fixtures/placetel/me.json").read_text())
CASES = [
    ("get_me", {}, "GET", "/me", 200, ME),
    ("list_contacts", {}, "GET", "/contacts", 200, []),
    ("get_contact", {"contact_id": 7}, "GET", "/contacts/7", 200, {"id": 7}),
    ("create_contact", {"first_name": "Jane", "email_work": "jane@example.org", "blocked": False, "tags": ["Sales"], "user_id": 15}, "POST", "/contacts", 201, {"id": 7, "first_name": "Jane"}),
    ("update_contact", {"contact_id": 7, "phone_work": "02211234589"}, "PUT", "/contacts/7", 200, {"id": 7}),
    ("delete_contact", {"contact_id": 7}, "DELETE", "/contacts/7", 204, None),
    ("list_calls", {}, "GET", "/calls", 200, []),
    ("get_call", {"call_id": 7}, "GET", "/calls/7", 200, {"id": 7}),
    ("initiate_call", {"sipuid": "7771234567@fpbx.de", "target": "02211234589"}, "POST", "/calls", 201, {"id": 7}),
    ("delete_call", {"call_id": 7}, "DELETE", "/calls/7", 204, None),
    ("list_numbers", {}, "GET", "/numbers", 200, []),
    ("get_number", {"number_id": 7}, "GET", "/numbers/7", 200, {"id": 7}),
    ("list_sip_users", {}, "GET", "/sip_users", 200, []),
    ("get_sip_user", {"sip_user_id": 7}, "GET", "/sip_users/7", 200, {"id": 7}),
    ("list_groups", {}, "GET", "/groups", 200, []),
    ("get_group", {"group_id": 7}, "GET", "/groups/7", 200, {"id": 7}),
    ("create_group", {"name": "Sales", "type": "ring_all", "member_ids": [7, 8]}, "POST", "/groups", 201, {"id": 7}),
    ("update_group", {"group_id": 7, "member_ids": []}, "PUT", "/groups/7", 200, {"id": 7}),
    ("delete_group", {"group_id": 7}, "DELETE", "/groups/7", 204, None),
    ("list_recordings", {}, "GET", "/recordings", 200, []),
    ("get_recording", {"recording_id": 7}, "GET", "/recordings/7", 200, {"id": 7}),
    ("list_faxes", {}, "GET", "/faxes", 200, []),
    ("get_fax", {"fax_id": 7}, "GET", "/faxes/7", 200, {"id": 7}),
    ("send_fax", {"from_number": "02211234589", "to_number": "02221234589", "email": "john@example.org", "file": "data:application/pdf;base64,JVBERi0xLjc="}, "POST", "/faxes", 201, {"id": 7}),
    ("send_sms", {"recipient": "02211234589", "message": "Hello"}, "POST", "/sms", 201, None),
]


def native(operation, config=None, credentials=AUTH):
    return NodeFactory.create_node(node_id="placetel-test", node_type="automation-placetel",
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": credentials})


@pytest.fixture
def http(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.placetel.de"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        code, payload = reply
        return httpx.Response(code, **({"json": payload} if payload is not None else {}))
    real = httpx.AsyncClient
    monkeypatch.setattr(node.httpx, "AsyncClient", lambda **kw: real(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,status,payload", CASES)
async def test_native_operation_wire_contract(http, operation, config, method, path, status, payload):
    requests, replies = http
    replies.append((status, payload))
    result = await native(operation, config).execute({})
    assert result == {"status": "success", "success": True, "data": payload, "status_code": status}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == "/v2" + path
    if method in {"POST", "PUT"}:
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {k: v for k, v in config.items() if k not in {"contact_id", "group_id", "call_id", "fax_id", "number_id", "sip_user_id", "recording_id"}}
    else:
        assert not request.content
    assert not replies


@pytest.mark.asyncio
async def test_pagination_and_exact_bracketed_filter_names(http):
    requests, replies = http
    replies.extend([(200, []), (200, []), (200, [])])
    await native("list_contacts", {"page": 3, "per_page": 20, "filter_blocked": False, "filter_email_work": "john@example.org", "search_number": "02211234589"}).execute({})
    assert dict(requests[0].url.params) == {"page": "3", "per_page": "20", "filter[blocked]": "false", "filter[email_work]": "john@example.org", "search[number]": "02211234589"}
    await native("list_calls", {"filter_date": "2026-11-09", "filter_type": "missed", "order": "asc"}).execute({})
    assert requests[1].url.params["filter[date]"] == "2026-11-09"
    assert requests[1].url.params["filter[type]"] == "missed"
    await native("list_recordings", {"filter_direction": ["in", "out"]}).execute({})
    assert requests[2].url.params["filter[direction]"] == "in,out"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 422, 429, 500])
async def test_provider_rejections_do_not_succeed_or_retry(http, code):
    requests, replies = http
    replies.append((code, {"message": "Rejected: " + AUTH["api_key"]}))
    result = await native("get_me").execute({})
    assert result["status"] == "error" and result["status_code"] == code
    assert "Rejected" in result["error"]
    assert AUTH["api_key"] not in result["error"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_on_write_is_unknown_without_retry(http):
    requests, replies = http
    replies.append(httpx.ReadTimeout("private transport details"))
    result = await native("send_sms", {"recipient": "02211234589", "message": "Hello"}).execute({})
    assert result["success"] is False and result["write_outcome"] == "unknown"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_unexpected_success_body_cannot_prove_account(http):
    _, replies = http
    for payload in (None, [], {"error": "Key not accepted"}):
        replies.append((200, payload))
        assert (await native("get_me").execute({}))["success"] is False


def test_manual_credential_defaults_and_invalid_pastes():
    assert node.PlacetelAPIKeyCredential(api_key=" issued-key\n").credential_type == "placetel_api_key"
    assert node.PlacetelAPIKeyCredential(api_key=" issued-key\n").api_key == "issued-key"
    for token in ("", "<token>", "https://web.placetel.de/integrations/web_api", "Bearer issued-key", "abc\nxyz"):
        with pytest.raises(ValidationError):
            node.PlacetelAPIKeyCredential(api_key=token)


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../me"},
    {"operation": "get_contact", "contact_id": 0},
    {"operation": "list_contacts", "per_page": 101},
    {"operation": "list_contacts", "page": 0},
    {"operation": "initiate_call", "sipuid": "7771234567@fpbx.de"},
    {"operation": "send_sms", "recipient": "02211234589"},
    {"operation": "create_group", "name": "Sales", "type": "invalid"},
])
def test_bad_config_is_rejected_before_http(config):
    assert node.PlacetelNode.validate_config({"config": config, "credentials": AUTH})["valid"] is False


CALL_EVENTS = json.loads((Path(__file__).parent / "fixtures/placetel/call_events.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event_name", [(op, values[0]) for op, values in node.CALL_EVENTS.items()])
async def test_call_trigger_lifecycle_and_documented_payloads(http, operation, event_name):
    from urllib.parse import urlencode
    import hashlib
    import hmac
    requests, replies = http
    config = {"operation": operation, "signing_secret": "THE_SECRET", "numbers": ["+4922129191999"]}
    replies.append((200, {"id": "sub-112ba1"}))
    registered = await node.PlacetelNode._register_external_webhook(
        webhook_url="https://example.org/callback", credential=AUTH, config=config, node_id="test")
    assert registered == {"external_webhook_id": "sub-112ba1", "signing_secret": "THE_SECRET"}
    assert requests[0].method == "PUT" and requests[0].url.path == "/v2/subscriptions"
    assert json.loads(requests[0].content) == {"service": "NoClick test", "url": "https://example.org/callback",
        "numbers": ["+4922129191999"], "phone": False,
        **{flag: kind == event_name for kind, flag in node.CALL_EVENTS.values()}}
    payload = CALL_EVENTS[event_name]
    raw = urlencode(payload).encode()
    headers = {"X-PLACETEL-SIGNATURE": hmac.new(b"THE_SECRET", raw, hashlib.sha256).hexdigest()}
    assert node.PlacetelNode.verify_webhook_signature(raw, headers, config)
    assert not node.PlacetelNode.verify_webhook_signature(raw + b" ", headers, config)
    assert not node.PlacetelNode.verify_webhook_signature(raw, {}, config)
    assert not node.PlacetelNode.verify_webhook_signature(raw, headers, {})
    for delivery in (payload, {"raw": raw}, {"raw": raw.decode()}):
        assert node.PlacetelNode.filter_trigger_payload(delivery, config)
        output = node.PlacetelNode.resolve_trigger_payload(delivery, config)
        assert output == payload
        event = node.PlacetelNode.resolve_agent_event(output)
        assert event["conversation_key"] == payload["call_id"]
        assert all(payload[key] in event["text"] for key in ("from", "to", "call_id"))
        if event_name == "HungUp":
            assert "missed" in event["text"] and "0 seconds" in event["text"]
    for other in CALL_EVENTS.values():
        assert node.PlacetelNode.filter_trigger_payload(other, config) == (other["event"] == event_name)
    assert not node.PlacetelNode.filter_trigger_payload({"raw": "event=Unknown"}, config)
    assert not node.PlacetelNode.filter_trigger_payload({"event": event_name}, config)
    assert (await native(operation, {"signing_secret": "THE_SECRET"}).execute({"spoofed": payload}))["status"] == "no_event"
    replies.append((204, None))
    await node.PlacetelNode._unregister_external_webhook(credential=AUTH, config={**config, **registered}, node_id="test")
    assert requests[-1].method == "DELETE" and requests[-1].url.path == "/v2/subscriptions/sub-112ba1"
    assert len(requests) == 2


def test_provider_published_signature_example():
    raw = b"call_id=4a4cbb39578170aed9a2761a7bec8c7e704a541f52291ef603d6f5f152980c3c&direction=in&event=CallAccepted&from=0123456789&to=0987654321"
    signature = "a16d490518344c33afa96158d115b48a26a250da6b8c6bc1d6dedb0a47d13eaa"
    assert node.PlacetelNode.verify_webhook_signature(raw,
        {"x-placetel-signature": signature}, {"signing_secret": "THE_SECRET"})
    assert node.PlacetelNode.resolve_agent_event({"raw": raw})["conversation_key"].startswith("4a4c")


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {}), (200, {}), (200, {"id": None})])
async def test_subscription_registration_rejects_errors_and_missing_ids(http, status, payload):
    requests, replies = http
    replies.append((status, payload))
    with pytest.raises(ValueError):
        await node.PlacetelNode._register_external_webhook(webhook_url="https://example.org/callback",
            credential=AUTH, config={"operation": "on_incoming_call", "signing_secret": "THE_SECRET"}, node_id="test")
    assert len(requests) == 1


def test_call_trigger_scope_changes_with_numbers_and_secret():
    from utils.webhook_manager import registration_fingerprint
    config = {"numbers": ["+4922129191999"], "signing_secret": "THE_SECRET"}
    before = registration_fingerprint(node.PlacetelNode, "on_incoming_call", "credential", config)
    for change in ({"numbers": ["+4922129191998"]}, {"signing_secret": "new-secret"}):
        assert registration_fingerprint(node.PlacetelNode, "on_incoming_call", "credential", {**config, **change}) != before
