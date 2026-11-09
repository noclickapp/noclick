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
