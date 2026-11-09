"""Native factory request/response regressions. Synthetic credentials; no live writes."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import roezan_sms_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/roezan-sms/requests.json").read_text())
SECRET = "synthetic-roezan-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="roezan-fixture", node_type="automation-roezan-sms",
        node_data={"config": config, "credentials": {"credential_type": "roezan_sms_api_key", "api_key": SECRET}})


def transport(monkeypatch, responder):
    calls = []
    def reply(request):
        calls.append(request)
        return responder(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
async def test_all_documented_operations_through_factory(monkeypatch, case):
    operation, config, method, path, payload, code, body = case
    calls = transport(monkeypatch, lambda _: httpx.Response(code, json=body) if body is not None else httpx.Response(code))
    result = await node({"operation": operation, **config}).execute({})
    assert result == {"status": "success", "http_status": code, "data": body}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == path
    assert request.url.scheme == "https" and request.url.host == "app.roezan.com"
    assert request.headers["x-api-key"] == SECRET
    assert SECRET not in str(result)
    if method == "GET":
        assert dict(request.url.params) == payload and not request.content
    else:
        assert (json.loads(request.content) if request.content else {}) == payload
    if config.get("idempotency_key"):
        assert request.headers["Idempotency-Key"] == config["idempotency_key"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 302, 401, 403, 404, 409, 422, 429, 500])
async def test_provider_rejections_and_no_automatic_retry(monkeypatch, code):
    calls = transport(monkeypatch, lambda _: httpx.Response(code, json={"error": "denied", "message": "Rejected " + SECRET}, headers={"Retry-After": "4", "Location": "https://example.com/"}))
    result = await node({"operation": "list_senders"}).execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert result["error"] == "Rejected [redacted]" and result["retry_after"] == "4"
    assert SECRET not in str(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"success": False, "message": "Bad key"}, {"error": "Bad key"}, {}, [], None])
async def test_bad_connection_responses_never_claim_success(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    assert (await node({"operation": "list_senders"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_media_only_and_stored_schedule_intent(monkeypatch):
    calls = transport(monkeypatch, lambda _: httpx.Response(200, json={"success": True}))
    await node({"operation": "send_message", "phone": "+19995550000", "media": ["https://link.to/picture.png"]}).execute({})
    assert json.loads(calls[0].content) == {"phone": "+19995550000", "media": ["https://link.to/picture.png"]}
    await node({"operation": "schedule_broadcast", "broadcast_id": 123}).execute({})
    assert json.loads(calls[1].content) == {}  # No implicit send_now.


@pytest.mark.asyncio
async def test_non_json_and_network_failure_are_honest(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, text="<html>login</html>"))
    assert (await node({"operation": "list_senders"}).execute({}))["status"] == "error"
    def timeout(request):
        raise httpx.ReadTimeout("private transport details " + SECRET, request=request)
    calls = transport(monkeypatch, timeout)
    result = await node({"operation": "send_message", "phone": "+19995550000", "message": "Hello"}).execute({})
    assert result["status"] == "error" and "unknown" in result["error"]
    assert SECRET not in str(result) and len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "send_message", "phone": "+19995550000"},
    {"operation": "get_contact"},
    {"operation": "get_contact_messages", "contact_id": "../other"},
    {"operation": "get_contact_messages", "contact_id": 1, "limit": 101},
    {"operation": "get_contact_messages", "contact_id": 1, "createdAtFrom": "2026-06-01"},
    {"operation": "schedule_broadcast", "broadcast_id": 1, "send_now": True, "scheduled_time": "2026-08-01 10:00"},
    {"operation": "create_broadcast", "name": "Draft", "message": "Hello", "list_ids": []},
    {"operation": "create_broadcast", "name": "Draft", "message": "Hello", "list_ids": [1], "scheduled_timezone": "America/New_York"},
    {"operation": "get_contact_lists", "contact_id": 0},
    {"operation": "custom_request", "url": "https://example.com"},
])
def test_invalid_configs(config):
    with pytest.raises((ValidationError, ValueError)):
        native.RoezanSMSNode.parse_config({"config": config})


def test_manual_credential_and_read_only_evidence():
    credential = native.RoezanSMSAPIKeyCredential(api_key="  " + SECRET + "  ")
    assert credential.api_key == SECRET and credential.credential_type == "roezan_sms_api_key"
    assert native.RoezanSMSNode.connection_evidence.operation == "list_senders"
    assert len(native.OPERATIONS) == len(CASES) == 19
    for bad in ["<token>", "https://example.com/key", "key\r\nforged", " "]:
        with pytest.raises(ValueError):
            native.RoezanSMSAPIKeyCredential(api_key=bad)
