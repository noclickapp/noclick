"""Offline requests through the real factory; contract examples are not live account evidence."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import hjarni_node as native
from nodes.core.registry import NodeFactory
from utils import ssrf

TOKEN = "hjarni-test-token-123456"
AUTH = {"credential_type": "hjarni_api_token", "api_token": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/hjarni/requests.json").read_text())


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "hjarni.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    client = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: client(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


def node(config):
    return NodeFactory.create_node(node_id="hjarni-test", node_type="automation-hjarni", node_data={"config": config, "credentials": AUTH})


@pytest.mark.asyncio
@pytest.mark.parametrize("op,arguments,method,path,body", CASES)
async def test_all_operations_use_exact_contract_route_and_body(transport, op, arguments, method, path, body):
    requests, replies = transport
    listing = op.startswith("list_") or op == "search_notes"
    status = 204 if method == "DELETE" else 201 if op.startswith("create_") else 200
    payload = [{"id":42,"title":"Review"}] if listing else {"user":{"id":1,"email_address":"alice@example.com"},"token":{"id":2,"name":"NoClick"}} if op == "get_me" else {"id":42,"title":"Review"}
    replies.append(httpx.Response(status, content=b"") if status == 204 else httpx.Response(status, json=payload, headers={"X-Total-Count":"1","X-Page":"1","X-Per-Page":"25"}))
    result = await node({"operation":op, **arguments}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v1" + path
    assert (json.loads(request.content) if request.content else None) == body
    if listing:
        assert result["items"] == payload and result["next_page"] is None
        assert request.url.params["page"] == "1" and request.url.params["per_page"] == "25"
    if op == "get_me":
        assert result["data"]["user"]["email_address"] == "alice@example.com"


@pytest.mark.asyncio
async def test_note_filters_and_pagination(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json=[{"id":42}], headers={"X-Total-Count":"80","X-Page":"2","X-Per-Page":"25"}))
    result = await node({"operation":"list_notes","page":2,"scope":"favorited","tag":"research","q":"a & b","container_id":12,"exclude_body":True}).execute({})
    assert result["next_page"] == 3 and result["pagination"]["total_count"] == 80
    assert dict(requests[0].url.params) == {"page":"2","per_page":"25","scope":"favorited","tag":"research","q":"a & b","container_id":"12","exclude_body":"true"}


@pytest.mark.asyncio
@pytest.mark.parametrize("config,expected", [
    ({"operation":"move_note","note_id":42}, {"container_id":None}),
    ({"operation":"update_note","note_id":42,"clear_tags":True,"clear_body":True}, {"note":{"tag_list":"","body":""}}),
    ({"operation":"update_note","note_id":42,"append_body":"More"}, {"note":{"append_body":"More"}}),
])
async def test_explicit_inbox_clear_and_append_semantics(transport, config, expected):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"id":42}))
    assert (await node(config).execute({}))["status"] == "success"
    assert json.loads(requests[0].content) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301,302,400,401,403,404,409,422,429,500])
async def test_errors_never_retry_writes_or_echo_credentials(transport, status):
    requests, replies = transport
    replies.append(httpx.Response(status, json={"error":"Denied " + TOKEN}, headers={"Location":"https://example.com","Retry-After":"30"}))
    result = await node({"operation":"create_note","title":"Review"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in json.dumps(result) and len(requests) == 1
    if status == 429:
        assert result["retry_after"] == "30"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(200, content=b"<html>login</html>",headers={"Content-Type":"text/html"}), httpx.Response(200,json=[]), httpx.Response(200,json={"error":"not accepted"}), httpx.ReadTimeout("timeout")])
async def test_account_probe_refuses_malformed_or_incomplete_response(transport, reply):
    _, replies = transport
    replies.append(reply)
    result = await node({"operation":"get_me"}).execute({})
    assert result["status"] == "error"


@pytest.mark.parametrize("config", [
    {"operation":"get_note","note_id":"../me"}, {"operation":"get_note","note_id":0},
    {"operation":"list_notes","per_page":101}, {"operation":"list_tags","page":0},
    {"operation":"create_note"}, {"operation":"search_notes","q":"test","search_scope":"other"},
    {"operation":"update_note","note_id":1,"body":"x","append_body":"y"},
    {"operation":"update_note","note_id":1,"clear_tags":True,"tag_list":"x"},
    {"operation":"list_tags","url":"https://example.com"},
])
def test_invalid_configs_fail_before_http(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_and_connection_contract():
    assert native.HjarniAPITokenCredential(api_token=TOKEN).credential_type == "hjarni_api_token"
    assert native.HjarniNode.connection_evidence.identity_operation == "get_me"
    assert native.HjarniNode.connection_evidence.identity_keys[0] == "email_address"
    for value in ["Bearer " + TOKEN, "https://example.com/token", "<token>", "bad\r\nheader"]:
        with pytest.raises(ValidationError) as exc:
            native.HjarniAPITokenCredential(api_token=value)
        assert value not in str(exc.value)
