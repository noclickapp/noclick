"""Published contract examples through the native factory, with intercepted HTTP."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import enrich_layer_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-enrich-layer-key-42"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/enrich-layer/responses.json").read_text())


def node(config):
    return NodeFactory.create_node(node_id="enrich-layer-fixture", node_type="automation-enrich-layer", node_data={"config": config, "credentials": {"credential_type": "enrich_layer_api_key", "api_key": TOKEN}})


def transport(monkeypatch, reply):
    calls = []
    def handle(request):
        calls.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES, ids=lambda operation: "enrich-layer-" + operation)
async def test_documented_queries_and_responses(monkeypatch, operation):
    fixture = FIXTURES[operation]
    calls = transport(monkeypatch, fixture["response"])
    result = await node(fixture["config"]).execute({})
    assert result["status"] == "success" and result["data"] == fixture["response"]
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "GET" and str(request.url).split("?")[0] == native.API_BASE + fixture["path"]
    assert dict(request.url.params) == {k: v for k, v in fixture["config"].items() if k != "operation"}
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(request.url) and request.content == b""


@pytest.mark.asyncio
async def test_connection_free_account_balance_accepts_zero(monkeypatch):
    calls = transport(monkeypatch, {"credit_balance": 0})
    result = await node({"operation": "get_credit_balance"}).execute({})
    assert result["status"] == "success" and result["items"] == [{"name": "0 credits remaining"}]
    assert str(calls[0].url) == native.API_BASE + "/api/v2/credit-balance"
    assert native.EnrichLayerNode.connection_evidence.proves == "account"
    assert native.EnrichLayerNode.connection_evidence.operation == "get_credit_balance"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400,401,403,404,429,500,503])
async def test_errors_preserved_redacted_and_never_retried(monkeypatch, code):
    calls = transport(monkeypatch, lambda _: httpx.Response(code, json={"message": "provider says " + TOKEN}, headers={"Retry-After": "60"}))
    result = await node({"operation": "get_credit_balance"}).execute({})
    assert result["status"] == "error" and result["status_code"] == code
    assert result["error"]["message"] == "provider says [redacted]" and TOKEN not in str(result)
    assert len(calls) == 1
    if code == 429: assert result["retry_after"] == "60"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(302, headers={"Location": "https://other.example"}), httpx.Response(200, text="<html>error</html>"), httpx.Response(200, content=b"{", headers={"Content-Type": "application/json"}), httpx.Response(200, json=[]), httpx.Response(200, json={}), httpx.Response(200, json={"credit_balance": True}), httpx.Response(200, json={"credit_balance": -1}), httpx.Response(200, json={"error": "not authorized"})])
async def test_invalid_connection_responses_do_not_verify(monkeypatch, reply):
    calls = transport(monkeypatch, lambda _: reply)
    assert (await node({"operation": "get_credit_balance"}).execute({}))["status"] == "error"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_timeout_never_retries_or_exposes_token(monkeypatch):
    def timeout(request): raise httpx.ReadTimeout("synthetic " + TOKEN, request=request)
    calls = transport(monkeypatch, timeout)
    result = await node(FIXTURES["get_company"]["config"]).execute({})
    assert result["status"] == "error" and TOKEN not in str(result) and len(calls) == 1


@pytest.mark.asyncio
async def test_continuations_are_explicit_and_never_followed(monkeypatch):
    payload = {"employees": [], "next_page": "https://untrusted.example/private"}
    calls = transport(monkeypatch, payload)
    result = await node({"operation": "list_employees", "url": "https://www.linkedin.com/company/google/", "after": "cursor-42"}).execute({})
    assert result["data"] == payload and len(calls) == 1
    assert calls[0].url.params["after"] == "cursor-42"


@pytest.mark.parametrize("key", ["", "Bearer abc", "https://example.com/key", "<token>"])
def test_invalid_keys_cannot_connect(key):
    with pytest.raises(ValidationError): native.EnrichLayerAPIKeyCredential(api_key=key)


def test_manual_discriminator_default_and_unknown_inputs():
    assert native.EnrichLayerAPIKeyCredential(api_key=TOKEN).credential_type == "enrich_layer_api_key"
    with pytest.raises(ValidationError): native.EnrichLayerGetCompany(url="https://www.linkedin.com/company/google/", arbitrary="value")
    with pytest.raises(ValidationError): native.EnrichLayerGetCompany()
    with pytest.raises(ValidationError): native.EnrichLayerGetPerson()
