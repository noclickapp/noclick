"""Native node execution with provider-authored fixtures and intercepted HTTP."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import debounce_node as db
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "debounce_api_key", "api_key": "fixture-debounce-secret"}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/debounce/responses.json").read_text())


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return httpx.Response(status, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(db, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(config, credential=AUTH):
    node = NodeFactory.create_node(node_id="debounce-test", node_type="automation-debounce", node_data={"config": config, "credentials": credential})
    return await node.execute({})


CASES = [
    ("validate_email", {"email": "someemail@gmail.com"}, "validateEmail_example", "api", "/v1/", {}),
    ("validate_with_photo", {"email": "someemail@gmail.com"}, "validateEmail_example", "api", "/v1/", {"photo": "true"}),
    ("validate_with_enrichment", {"email": "someemail@gmail.com"}, "validateEmail_example", "api", "/v1/", {"append": "true"}),
    ("validate_gsuite", {"email": "someemail@gmail.com"}, "validateEmail_example", "api", "/v1/", {"gsuite": "true"}),
    ("reverse_email_lookup", {"email": "someemail@gmail.com"}, None, "api", "/v1/reverse/", {}),
    ("upload_bulk_list", {"url": "https://example.com/emails.csv"}, "uploadBulkList_success", "bulk", "/v1/upload/", {}),
    ("check_bulk_status", {"list_id": "20664"}, "checkBulkStatus_completed", "bulk", "/v1/status/", {}),
    ("get_balance", {}, "getBalance_success", "api", "/v1/balance/", {}),
    ("get_usage", {"start": "24-01-01", "end": "24-12-31"}, "getUsage_example", "api", "/v1/usage/", {}),
    ("check_disposable_email", {"email": "example.com"}, "checkDisposableEmail_example", "disposable", "/", {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,fixture,host,path,flags", CASES)
async def test_debounce_actions(transport, operation, config, fixture, host, path, flags):
    requests, replies = transport
    body = FIXTURES[fixture] if fixture else {"email": "someemail@gmail.com", "data": {"name": "Example"}, "success": 1}
    replies.append((200, body))
    result = await run({"operation": operation, **config})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.host == host + ".debounce.io"
    assert request.url.path == path
    params = dict(request.url.params)
    expected = {**config, **flags}
    if operation == "validate_email":
        expected.update(photo="false", append="false", gsuite="false")
    if host != "disposable":
        expected["api"] = AUTH["api_key"]
    assert params == expected
    assert AUTH["api_key"] not in json.dumps(result)
    assert "api" not in result.get("debounce", {})


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", ["getBalance_success", "getBalance_prose"])
async def test_debounce_balance_contract_and_prose(transport, fixture):
    transport[1].append((200, FIXTURES[fixture]))
    out = await run({"operation": "get_balance"})
    assert out["status"] == "success"
    assert str(out["balance"]).isdigit()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [200, 401, 402, 429])
async def test_debounce_provider_rejection(transport, code):
    transport[1].append((code, {"debounce": {"error": "Wrong API"}, "success": "0"}))
    out = await run({"operation": "get_balance"})
    assert out["status"] == "error"
    assert out["error"] == "Wrong API"


@pytest.mark.asyncio
async def test_debounce_exception_url_does_not_leak(transport):
    transport[1].append(httpx.ConnectError("https://api.debounce.io/?api=" + AUTH["api_key"]))
    out = await run({"operation": "get_balance"})
    assert out["status"] == "error"
    assert AUTH["api_key"] not in json.dumps(out)


@pytest.mark.asyncio
async def test_debounce_usage_echo_redacted(transport):
    transport[1].append((200, {"success": "1", "debounce": {"api": AUTH["api_key"], "calls": "100", "message": AUTH["api_key"]}}))
    out = await run({"operation": "get_usage", "start": "24-01-01", "end": "24-12-31"})
    assert out["debounce"]["calls"] == "100"
    assert AUTH["api_key"] not in json.dumps(out)


@pytest.mark.asyncio
async def test_debounce_disposable_never_sends_credential(transport):
    transport[1].append((200, {"disposable": "false"}))
    assert (await run({"operation": "check_disposable_email", "email": "example.com"}, None))["status"] == "success"
    assert "api" not in transport[0][0].url.params


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"balance": True}, {"balance": -1}, {"balance": "oops"}])
async def test_debounce_bad_balance_not_evidence(transport, body):
    transport[1].append((200, body))
    assert (await run({"operation": "get_balance"}))["status"] == "error"


@pytest.mark.parametrize("config", [
    {"operation": "upload_bulk_list", "url": "http://example.com/list.csv"},
    {"operation": "upload_bulk_list", "url": "https://example.com/page"},
    {"operation": "validate_email", "email": "no-email"},
    {"operation": "get_usage", "start": "24-01-01", "end": "23-01-01"},
    {"operation": "get_usage", "start": "20-08-13", "end": "24-01-01"},
    {"operation": "get_usage", "start": "24-13-01", "end": "24-01-01"},
])
def test_debounce_invalid_config(config):
    with pytest.raises(ValidationError):
        db.DebounceFullConfig(config=config, credentials=AUTH)


def test_debounce_secret_shape():
    assert db.DebounceAPIKeyCredential(api_key="  fixture-debounce-secret  ").api_key == AUTH["api_key"]
    with pytest.raises(ValidationError):
        db.DebounceAPIKeyCredential(api_key="https://example.com")
