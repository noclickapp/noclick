"""Exercise Strale's one-request operation mappings without network access.

Check execution status, provider errors, manual credentials and cap patch semantics.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
import nodes.strale_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/strale/requests.json").read_text())
CREDENTIAL = {"credential_type": "strale_api_key", "api_key": "sk_live_mock_secret"}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="strale-test", node_type="automation-strale",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_operation_mapping(monkeypatch, operation):
    case = CASES[operation]
    payload = {"balance_cents": 1850, "currency": "EUR"} if operation == "get_wallet_balance" else {"result": {"status": "completed"}}
    calls = transport(monkeypatch, payload, 201 if operation == "create_api_key" else 200)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == payload
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert request.url.path == case["path"]
    assert request.url.host == "api.strale.io"
    assert request.headers["authorization"] == "Bearer " + CREDENTIAL["api_key"]
    if operation == "update_api_key":
        assert json.loads(request.content) == {"max_spend_total_cents": None, "max_spend_per_hour_cents": 0}
    elif request.method in {"POST", "PATCH"}:
        assert json.loads(request.content) == case["body"]
    elif request.method == "GET":
        expected = {k: str(v) for k,v in case["config"].items() if k not in {"operation", "id", "slug"}}
        assert dict(request.url.params) == expected
    else:
        assert not request.content
    if operation == "get_wallet_balance":
        assert result["items"] == [{"name": "18.50 EUR wallet"}]


@pytest.mark.asyncio
async def test_pending_execution_returns_without_poll_or_retry(monkeypatch):
    payload = {"status": "pending", "transaction_id": "123e4567-e89b-12d3-a456-426614174000", "poll_url": "/v1/transactions/123e4567-e89b-12d3-a456-426614174000"}
    calls = transport(monkeypatch, payload, 202)
    result = await node(CASES["execute_capability"]["config"]).execute({})
    assert result["data"] == payload and result["http_status"] == 202
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 301, 401, 403, 429, 500])
async def test_error_cannot_be_connection_evidence(monkeypatch, status):
    calls = transport(monkeypatch, {"error_code": "unauthorized", "message": "Rejected " + CREDENTIAL["api_key"]}, status)
    result = await node({"operation": "get_wallet_balance"}).execute({})
    assert result["status"] == "error" and "items" not in result
    assert CREDENTIAL["api_key"] not in str(result)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_malformed_balance_is_not_proof(monkeypatch):
    transport(monkeypatch, {"currency": "EUR"})
    with pytest.raises(ValueError, match="wallet balance"):
        await node({"operation": "get_wallet_balance"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_capability", "slug": "../wallet/balance"},
    {"operation": "get_transaction", "id": "../api-keys"},
    {"operation": "execute_batch", "capability_slug": "vat-validate", "inputs": [], "max_total_price_cents": 10},
    {"operation": "create_api_key", "label": "bad\nlabel"},
    {"operation": "update_api_key", "id": "123e4567-e89b-12d3-a456-426614174000"},
])
def test_invalid_input(config):
    with pytest.raises(ValueError):
        native.StraleNode.parse_config({"config": config, "credentials": CREDENTIAL})


def test_manual_key_default_and_cleaning():
    assert native.StraleAPIKeyCredential(api_key="  sk_live_mock_secret  ").api_key == CREDENTIAL["api_key"]
    assert native.StraleAPIKeyCredential(api_key=CREDENTIAL["api_key"]).credential_type == "strale_api_key"
    for value in ["Bearer secret", "https://example.test", "bad\r\nheader"]:
        with pytest.raises(ValidationError):
            native.StraleAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_transaction_error_field_is_data(monkeypatch):
    payload = {"id": "123e4567-e89b-12d3-a456-426614174000", "status": "failed", "error": "Execution failed"}
    transport(monkeypatch, payload)
    result = await node(CASES["get_transaction"]["config"]).execute({})
    assert result["status"] == "success" and result["data"] == payload
