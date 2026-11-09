"""Offline contract regressions using the provider examples cited in fixtures."""
import json
from pathlib import Path
import httpx
import pytest
from nodes.core.base import ConfigValidationError
from nodes import proxiedmail_node as native
from nodes.core.registry import NodeFactory

TOKEN = "proxiedmail-unit-test-token"
CASES = json.loads((Path(__file__).parent / "fixtures/proxiedmail/operations.json").read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id="proxiedmail-test", node_type="automation-proxiedmail", node_data={
        "config": config, "credentials": {"credential_type": "proxiedmail_api_token", "api_token": TOKEN}})

def transport(monkeypatch, reply):
    calls = []
    def handler(request):
        calls.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls

@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_documented_requests_and_responses(monkeypatch, case):
    calls = transport(monkeypatch, lambda _: httpx.Response(case["http_status"], json=case["response"]))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == case["response"]
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert str(request.url) == native.BASE + case["path"]
    assert request.headers["Token"] == TOKEN and "authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["config"]["operation"] == "list_proxy_bindings":
        assert result["items"][0]["proxy_address"] == "v7do1zfs8w@proxiedmail.com"

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 404, 429, 500])
async def test_rejection_preserves_provider_message_without_token_or_retries(monkeypatch, status):
    calls = transport(monkeypatch, lambda _: httpx.Response(status, text="Denied " + TOKEN, headers={"Location": "https://example.com"}))
    result = await node({"operation": "list_proxy_bindings"}).execute({})
    assert len(calls) == 1 and result["status"] == "error"
    assert result["error"] == "Denied [redacted]" and result["http_status"] == status

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"data": {}}, {"data": None}])
async def test_malformed_list_is_not_connection_evidence(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    with pytest.raises(ValueError): await node({"operation": "list_proxy_bindings"}).execute({})

@pytest.mark.asyncio
async def test_null_callback_and_empty_list_are_valid(monkeypatch):
    body = {"status": "ok", "payload": None, "code": "ok", "is_received": False, "method": None}
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    assert (await node({"operation": "get_callback", "callback_hash": "receiver"}).execute({}))["data"] == body
    transport(monkeypatch, lambda _: httpx.Response(200, json={"data": []}))
    assert (await node({"operation": "list_proxy_bindings"}).execute({}))["items"] == []

@pytest.mark.asyncio
async def test_nested_secret_and_error_envelopes(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={"errors": [{"message": TOKEN}]}))
    result = await node({"operation": "list_proxy_bindings"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)

@pytest.mark.asyncio
async def test_write_timeout_never_retries(monkeypatch):
    def timeout(request): raise httpx.ReadTimeout(TOKEN, request=request)
    calls = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="inspect write outcomes") as exc: await node(CASES[1]["config"]).execute({})
    assert len(calls) == 1 and TOKEN not in str(exc.value)

@pytest.mark.parametrize("config", [
    {"operation": "get_received_email", "received_email_id": "../secret"},
    {"operation": "get_callback", "callback_hash": "x?y=1"},
    {"operation": "update_proxy_binding", "proxy_binding_id": "id"},
    {"operation": "set_callback_url", "proxy_binding_id": "id", "callback_url": "http://example.com"},
    {"operation": "set_forwarding_addresses", "proxy_binding_id": "id", "real_addresses": {"bad": True}},
])
def test_invalid_inputs_fail_before_request(config):
    with pytest.raises(ConfigValidationError): node(config)

def test_credential_is_manually_connectable_and_has_default_type():
    c = native.ProxiedmailAPITokenCredential(api_token=TOKEN)
    assert c.credential_type == "proxiedmail_api_token"
    assert set(native.ProxiedmailAPITokenCredential.model_fields) == {"credential_type", "api_token"}
