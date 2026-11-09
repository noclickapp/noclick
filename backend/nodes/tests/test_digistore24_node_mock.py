"""Offline regressions for Digistore24's published API contract."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import digistore24_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-digistore24-test-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="digistore24-test", node_type="automation-digistore24",
        node_data={"config": config, "credentials": {"api_key": KEY, "credential_type": "digistore24_api_key"}})


def transport(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", [
    ({"operation": "get_user_info"}, "GET", "getUserInfo", {}, None),
    ({"operation": "list_products"}, "GET", "listProducts", {"sort_by": "name"}, None),
    ({"operation": "get_product", "product_id": 39}, "GET", "getProduct", {"product_id": "39"}, None),
    ({"operation": "list_buyers", "page_no": 2, "page_size": 10}, "GET", "listBuyers", {"page_no": "2", "page_size": "10"}, None),
    ({"operation": "get_buyer", "buyer_id": 20}, "GET", "getBuyer", {"buyer_id": "20"}, None),
    ({"operation": "update_buyer", "buyer_id": 20, "first_name": "Claus"}, "PUT", "updateBuyer", {"buyer_id": "20"}, {"first_name": "Claus"}),
    ({"operation": "list_purchases"}, "GET", "listPurchases", {"from": "-24h", "to": "now", "sort_by": "date", "sort_order": "asc", "load_transactions": "false", "page_no": "1", "page_size": "500"}, None),
    ({"operation": "get_purchase", "purchase_id": "ABC123"}, "GET", "getPurchase", {"purchase_id": "ABC123"}, None),
    ({"operation": "stop_rebilling", "purchase_id": "ABC123"}, "POST", "stopRebilling", {"purchase_id": "ABC123", "force": "false", "ignore_refund_possibility": "false"}, None),
    ({"operation": "start_rebilling", "purchase_id": "ABC123"}, "POST", "startRebilling", {"purchase_id": "ABC123"}, None),
    ({"operation": "list_transactions"}, "GET", "listTransactions", {"from": "-24h", "to": "now", "sort_by": "date", "sort_order": "asc", "page_no": "1", "page_size": "500"}, None),
    ({"operation": "list_vouchers"}, "GET", "listVouchers", {}, None),
    ({"operation": "get_voucher", "code": "SALE + 10"}, "GET", "getVoucher", {"code": "SALE + 10"}, None),
    ({"operation": "create_voucher", "code": "SALE10", "first_rate": 10}, "POST", "createVoucher", {}, {"code": "SALE10", "first_rate": 10.0, "product_ids": "all", "is_count_limited": False, "count_left": 1, "upgrade_policy": "valid"}),
    ({"operation": "delete_voucher", "code": "SALE10"}, "DELETE", "deleteVoucher", {"code": "SALE10"}, None),
])
async def test_exact_contract_request_and_single_call(monkeypatch, config, method, path, query, body):
    requests = transport(monkeypatch, {"result": "success", "data": {"user_id": 12345, "user_name": "fixture-vendor"}})
    result = await node(config).execute({})
    assert result["status"] == "success" and result["readback_verified"] is False
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and str(req.url).split("?")[0] == native.BASE + "/" + path
    assert dict(req.url.params) == query
    assert req.headers["X-DS-API-KEY"] == KEY
    assert KEY not in str(req.url) and KEY not in str(result)
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"result": "error", "code": 2, "message": "Invalid API key"},
    {"result": "error", "code": 5, "message": "Permission denied"},
    {"action": "show_message", "status": "error", "http_code": 400, "data": [], "message": "Invalid field"},
])
async def test_http_200_error_envelope_is_failure(monkeypatch, payload):
    requests = transport(monkeypatch, payload)
    result = await node({"operation": "get_user_info"}).execute({})
    assert result["status"] == "error" and result["success"] is False
    assert result["error"] == payload["message"] and len(requests) == 1


@pytest.mark.asyncio
async def test_page_preserved_without_hidden_fetch(monkeypatch):
    page = {"page_no": 2, "page_size": 10, "page_count": 3, "item_count": 21, "items": [{"id": 20}]}
    requests = transport(monkeypatch, {"result": "success", "data": page})
    result = await node({"operation": "list_buyers", "page_no": 2, "page_size": 10}).execute({})
    assert result["data"] == page and len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_does_not_retry_mutation(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("synthetic timeout"))
    result = await node({"operation": "start_rebilling", "purchase_id": "ABC123"}).execute({})
    assert result["status"] == "unknown" and result["write_outcome"] == "unverified" and len(requests) == 1


@pytest.mark.asyncio
async def test_provider_reflected_secret_is_redacted(monkeypatch):
    transport(monkeypatch, {"result": "error", "code": 2, "message": "Rejected " + KEY})
    result = await node({"operation": "get_user_info"}).execute({})
    assert KEY not in str(result) and "[redacted]" in result["error"]


@pytest.mark.parametrize("config", [
    {"operation": "get_product", "product_id": 0},
    {"operation": "list_buyers", "page_no": 0},
    {"operation": "list_transactions", "page_size": 1001},
    {"operation": "update_buyer", "buyer_id": 20},
    {"operation": "create_voucher", "code": "SALE", "first_rate": 101},
    {"operation": "stop_rebilling", "purchase_id": "ABC123", "force": "yes"},
])
def test_invalid_configs(config):
    with pytest.raises(ValidationError):
        native.Digistore24FullConfig.model_validate({"config": config, "credentials": {"api_key": KEY}})


def test_manual_credential_defaults_and_secret_shaping():
    credential = native.Digistore24APIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == "digistore24_api_key" and credential.api_key == KEY
    for value in ("https://example.com/key", "<token>", "abc\nxyz"):
        with pytest.raises(ValidationError):
            native.Digistore24APIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_empty_account_response_cannot_prove_connection(monkeypatch):
    transport(monkeypatch, {"result": "success", "data": {}})
    result = await node({"operation": "get_user_info"}).execute({})
    assert result["status"] == "error" and result["success"] is False
