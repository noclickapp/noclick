"""Offline request, response and credential regressions for Greenfield v1."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import btcpay_server_node as native
from nodes.core.registry import NodeFactory

TOKEN = "fixture-btcpay-key-123456"
CREDENTIAL = {"credential_type": "btcpay_server_api_key", "api_base_url": "https://pay.example.com", "api_key": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/btcpay-server/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="btcpay-fixture", node_type=native.BtcpayServerNode.integration_type,
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, response):
    requests = []
    def handle(request):
        requests.append(request)
        return response(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: "btcpay-server/" + case["config"]["operation"])
async def test_btcpay_server_contract_routes_bodies_and_output(monkeypatch, case):
    action = case["config"]["operation"]
    body = [] if action in native.LIST_RESPONSES else {"id": "resource-1", "name": "Fixture account"}
    requests = transport(monkeypatch, lambda req: httpx.Response(200, content=b"" if action in native.EMPTY_RESPONSES else json.dumps(body).encode(), headers={"Content-Type": "application/json"}))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"] and req.url.path == case["path"]
    assert req.url.host == "pay.example.com"
    assert req.headers["Authorization"] == "token " + TOKEN
    assert list(req.url.params.multi_items()) == list(map(tuple, case.get("query", [])))
    assert (json.loads(req.content) if req.content else None) == case.get("body")
    assert TOKEN not in str(result)
    assert result.get("data") == (None if action in native.EMPTY_RESPONSES else body)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_btcpay_server_rejects_http_errors_without_retry_or_follow(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={"message": "Rejected " + TOKEN}, headers={"Location": "https://elsewhere.example/"}))
    result = await node({"operation": "create_invoice", "store_id": "store-1", "amount": "5.00", "currency": "USD"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert len(requests) == 1 and "data" not in result and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, [], "unexpected", {"code": "bad-key", "message": "Rejected"}])
async def test_btcpay_server_malformed_resource_is_not_success(monkeypatch, body):
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "error" and "data" not in result


@pytest.mark.asyncio
async def test_btcpay_server_timeout_write_is_uncertain_and_not_retried(monkeypatch):
    def fail(req):
        raise httpx.ReadTimeout("request " + TOKEN, request=req)
    requests = transport(monkeypatch, fail)
    result = await node({"operation": "archive_invoice", "invoice_id": "invoice-1"}).execute({})
    assert result["status"] == "unknown" and len(requests) == 1
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_btcpay_server_invoice_offset_and_repeated_order_filters(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=[{"id": "invoice-1"}]))
    result = await node({"operation": "list_invoices", "store_id": "store-1", "take": 1, "skip": 2, "order_ids": ["1000", "1001"]}).execute({})
    assert requests[0].url.params.get_list("orderId") == ["1000", "1001"]
    assert result["next_skip"] == 3 and result["has_more"] is None


@pytest.mark.asyncio
async def test_btcpay_server_redacts_echoed_key_recursively(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json={"id": "user-1", "name": TOKEN, "metadata": {TOKEN: [TOKEN]}}))
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "success" and TOKEN not in str(result)


@pytest.mark.parametrize("field,value", [("api_base_url", "http://pay.example.com"), ("api_base_url", "https://user:password@pay.example.com"), ("api_key", "token key"), ("api_key", "https://example.com/key"), ("api_key", "<token>"), ("api_key", "key\nheader")])
def test_btcpay_server_credential_validation(field, value):
    with pytest.raises(ValidationError):
        native.BtcpayServerAPIKeyCredential.model_validate({**CREDENTIAL, field: value})


def test_btcpay_server_credential_paste_and_evidence():
    cred = native.BtcpayServerAPIKeyCredential.model_validate({**CREDENTIAL, "api_base_url": " pay.example.com/account/apikeys ", "api_key": " " + TOKEN + "\n"})
    assert cred.api_base_url == "https://pay.example.com" and cred.api_key == TOKEN
    assert native.BtcpayServerNode.connection_evidence.identity_operation == "get_current_user"
    assert len(CASES) == 19


@pytest.mark.parametrize("config", [
    {"operation": "get_invoice", "invoice_id": "../other"},
    {"operation": "get_invoice", "invoice_id": "a?query=b"},
    {"operation": "create_invoice", "store_id": "store-1", "amount": "0", "currency": "USD"},
    {"operation": "mark_invoice_status", "invoice_id": "invoice-1", "status": "New"},
    {"operation": "list_invoices", "store_id": "store-1", "take": 101},
    {"operation": "get_current_user", "url": "https://elsewhere.example/"},
])
def test_btcpay_server_invalid_config(config):
    with pytest.raises(ValueError):
        native.BtcpayServerNode.parse_config({"config": config, "credentials": CREDENTIAL})
