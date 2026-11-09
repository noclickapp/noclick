"""Epos Now HTTP, hand-connect and polling regressions without a live account.

Synthetic records use the fields and shapes in the pinned provider OpenAPI v4
schemas; the conformance harness independently validates every operation.
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import epos_now_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-epos-key"
HTTPX_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="epos-test", node_type="automation-epos-now",
        node_data={"config": config, "credentials": {"api_key": TOKEN}})


def mock_http(monkeypatch, handler):
    requests = []
    original = HTTPX_CLIENT
    def respond(request):
        requests.append(request)
        return handler(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", [
    ({"operation": "list_customers", "page": 3}, "GET", "/api/v4/Customer", {"page": "3"}, None),
    ({"operation": "get_customer", "id": 12}, "GET", "/api/v4/Customer/12", {}, None),
    ({"operation": "find_customers_by_email", "email": "a+b@example.com"}, "GET", "/api/v4/Customer/GetByEmail", {"email": "a+b@example.com", "page": "1"}, None),
    ({"operation": "create_customer", "forename": "Ada", "emailAddress": "ada@example.com"}, "POST", "/api/v4/Customer", {}, [{"forename": "Ada", "emailAddress": "ada@example.com"}]),
    ({"operation": "update_customer", "id": 12, "forename": "Ada"}, "PUT", "/api/v4/Customer", {}, [{"id": 12, "forename": "Ada"}]),
    ({"operation": "list_products"}, "GET", "/api/v4/Product", {"page": "1"}, None),
    ({"operation": "get_product", "id": 25}, "GET", "/api/v4/Product/25", {}, None),
    ({"operation": "create_product", "name": "Coffee", "costPrice": 1, "salePrice": 3, "eatOutPrice": 4, "sellOnWeb": False}, "POST", "/api/v4/Product", {}, [{"name": "Coffee", "costPrice": 1, "salePrice": 3, "eatOutPrice": 4, "sellOnWeb": False}]),
    ({"operation": "update_product", "id": 25, "name": "Coffee", "costPrice": 1, "salePrice": 3, "eatOutPrice": 4}, "PUT", "/api/v4/Product", {}, [{"id": 25, "name": "Coffee", "costPrice": 1, "salePrice": 3, "eatOutPrice": 4}]),
    ({"operation": "list_categories"}, "GET", "/api/v4/Category", {"page": "1"}, None),
    ({"operation": "get_category", "id": 2}, "GET", "/api/v4/Category/2", {}, None),
    ({"operation": "create_category", "name": "Drinks", "parentId": 3}, "POST", "/api/v4/Category", {}, [{"name": "Drinks", "parentId": 3}]),
    ({"operation": "list_product_stock"}, "GET", "/api/v4/ProductStock", {"page": "1"}, None),
    ({"operation": "get_product_stock", "productId": 25, "locationId": 7}, "GET", "/api/v4/ProductStock/Product/25/Location/7", {}, None),
    ({"operation": "list_locations"}, "GET", "/api/v4/Location", {"page": "1"}, None),
    ({"operation": "get_location", "id": 7}, "GET", "/api/v4/Location/7", {}, None),
    ({"operation": "list_transactions", "status": 1}, "GET", "/api/v4/Transaction", {"page": "1", "status": "1"}, None),
    ({"operation": "list_transactions_by_date", "start_date": "2026-11-01T00:00:00Z", "end_date": "2026-11-02T00:00:00Z", "device_id": 3}, "GET", "/api/v4/Transaction/GetByDate", {"startDate": "2026-11-01T00:00:00Z", "endDate": "2026-11-02T00:00:00Z", "deviceId": "3", "page": "1"}, None),
    ({"operation": "get_transaction_by_reference", "referenceCode": "a/b ?"}, "GET", "/api/v4/Transaction/ReferenceCode/a/b ?", {}, None),
    ({"operation": "list_end_of_days"}, "GET", "/api/v4/EndOfDay", {"page": "1"}, None),
])
async def test_epos_now_exact_http_contract(monkeypatch, config, method, path, query, body):
    spec = native.OPERATIONS[config["operation"]]
    response = [{"id": 1}] if spec.array else {"id": 1}
    requests = mock_http(monkeypatch, lambda request: httpx.Response(200, json=response))
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == response
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.eposnowhq.com" and request.url.scheme == "https"
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert request.headers["Authorization"] == "Basic " + TOKEN
    assert len(requests) == 1
    if config["operation"] == "get_transaction_by_reference":
        assert b"a%2Fb%20%3F" in request.url.raw_path


def test_epos_now_manual_credential_default_and_secret_validation():
    assert native.EposNowAPIKeyCredential(api_key=TOKEN).credential_type == "epos_now_api_key"
    for token in ["Basic abc", "abc\ndef", "", "x y"]:
        with pytest.raises((ValidationError, ValueError)):
            native.EposNowAPIKeyCredential(api_key=token)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,valid", [(401, False), (403, False), (429, None), (500, None)])
async def test_epos_now_evidence_rejection_and_unknown(monkeypatch, status, valid):
    mock_http(monkeypatch, lambda request: httpx.Response(status, text="Provider refused " + TOKEN))
    result = await native.EposNowNode.validate_credential_access({"api_key": TOKEN})
    assert result["valid"] is valid
    assert TOKEN not in result["message"]


@pytest.mark.asyncio
async def test_epos_now_empty_page_and_bad_envelope(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=[]))
    assert (await node({"operation": "list_locations"}).execute({}))["next_page"] is None
    assert (await native.EposNowNode.validate_credential_access({"api_key": TOKEN}))["valid"] is True
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"error": "failed"}))
    with pytest.raises(ValueError, match="error envelope"):
        await node({"operation": "list_locations"}).execute({})


@pytest.mark.asyncio
async def test_epos_now_no_redirect_and_no_write_retry(monkeypatch):
    requests = mock_http(monkeypatch, lambda request: httpx.Response(302, headers={"Location": "https://example.com"}))
    with pytest.raises(ValueError, match="HTTP 302"):
        await node({"operation": "create_customer", "forename": "Ada"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_epos_now_poll_baselines_then_emits_once_and_scope_change_rebaselines(monkeypatch):
    rows = [{"id": 1, "customerId": 2, "deviceId": 3, "dateTime": "2026-11-10T00:00:00Z", "totalAmount": 4, "statusId": 1}]
    def respond(request):
        assert "startDate" in request.url.params and "endDate" in request.url.params
        assert request.url.params["deviceId"] == "3"
        return httpx.Response(200, json=rows if request.url.params["page"] == "1" else [])
    mock_http(monkeypatch, respond)
    n = node({"operation": "on_new_transaction", "device_id": 3})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    monkeypatch.setattr(n, "_update_node_state", update)
    assert (await n.execute({}))["new_transaction_count"] == 0
    rows.append({**rows[0], "id": 2})
    result = await n.execute({})
    assert [r["id"] for r in result["transactions"]] == [2]
    event = n.resolve_agent_event(result)
    assert "Transaction 2" in event["text"] and "customer 2" in event["text"]
    assert (await n.execute({}))["new_transaction_count"] == 0
    assert n.resolve_agent_event({"transactions": []}) is None
    n.config.config.lookback_hours = 48
    rows.append({**rows[0], "id": 3})
    assert (await n.execute({}))["new_transaction_count"] == 0


@pytest.mark.asyncio
async def test_epos_now_incomplete_poll_does_not_advance_state(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=[{"id": i} for i in range(200)]))
    n = node({"operation": "on_new_transaction"})
    async def must_not_filter(*args):
        pytest.fail("Incomplete polling must not consume IDs")
    monkeypatch.setattr(n, "_filter_unseen", must_not_filter)
    with pytest.raises(ValueError, match="repeated"):
        await n.execute({})
