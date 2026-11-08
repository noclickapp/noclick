"""Altoviz fixed-route, write-body, error and pagination regressions. No live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import altoviz_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-altoviz-key-42"
CREDENTIAL = {"credential_type": "altoviz_api_key", "api_key": TOKEN}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/altoviz/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="altoviz-test", node_type="automation-altoviz",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, *, headers=None, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda row: row["config"]["operation"])
async def test_contract_routes_and_json(monkeypatch, fixture):
    requests = transport(monkeypatch, fixture["response"])
    result = await node(fixture["config"]).execute({})
    assert result["data"] == fixture["response"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    assert request.url.host == "api.altoviz.com"
    assert request.url.path == fixture["path"]
    assert request.headers["X-API-KEY"] == TOKEN
    assert "apikey" not in request.url.params
    assert json.loads(request.content) == fixture["body"] if "body" in fixture else request.content == b""
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_paging_and_filters_are_one_page(monkeypatch):
    requests = transport(monkeypatch, [{"id": 42}], headers={"X-PAGE-NEXT": "/v1/Customers?PageIndex=3&PageSize=5&query=Acme"})
    result = await node({"operation": "list_customers", "page_index": 2, "page_size": 5, "query": "Acme"}).execute({})
    assert result["next_page_index"] == 3 and result["has_more"] is True
    assert dict(requests[0].url.params) == {"PageIndex": "2", "PageSize": "5", "query": "Acme"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["https://evil.example/v1/Customers?PageIndex=2", "/v1/Products?PageIndex=2", "/v1/Customers?PageIndex=1", "/v1/Customers?PageIndex=x", "/v1/Customers?PageIndex=2&PageIndex=3", "/v1/Customers?PageIndex=2&query=other"])
async def test_bad_pagination_never_followed(monkeypatch, link):
    requests = transport(monkeypatch, [], headers={"X-PAGE-NEXT": link})
    with pytest.raises(ValueError):
        await node({"operation": "list_customers"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_nested_dates_zero_false_and_explicit_metadata_removal(monkeypatch):
    requests = transport(monkeypatch, {"id": 42})
    await node({"operation": "update_invoice", "id": 42, "invoice": {
        "date": "2026-11-09", "useTaxIncludedPrices": False, "shippingAmount": 0,
        "metadata": {"obsolete": None, "empty": ""},
        "lines": [{"productId": 12, "quantity": 2, "taxExcludedPrice": 25}],
    }}).execute({})
    assert json.loads(requests[0].content) == {"date": "2026-11-09", "useTaxIncludedPrices": False,
        "shippingAmount": 0, "metadata": {"obsolete": None, "empty": ""},
        "lines": [{"productId": 12, "quantity": 2, "taxExcludedPrice": 25}]}


@pytest.mark.asyncio
async def test_documented_list_can_be_empty(monkeypatch):
    transport(monkeypatch, [])
    assert await node({"operation": "list_customers"}).execute({}) == {"data": [], "next_page_index": None, "has_more": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_http_errors_preserve_provider_diagnostic_and_hide_key(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status=status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "create_customer", "customer": {"companyName": "Acme"}}).execute({})
    assert TOKEN not in str(error.value) and str(status) in str(error.value)
    assert "Rejected" in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("list_customers", {}), ("list_customers", [1]), ("get_customer", []), ("get_customer", {"errors": ["bad"]})])
async def test_invalid_response_shapes(monkeypatch, operation, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": operation, **({"id": 1} if operation == "get_customer" else {})}).execute({})


@pytest.mark.asyncio
async def test_empty_write_is_rejected_before_network(monkeypatch):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="at least one field"):
        await node({"operation": "update_customer", "id": 1, "customer": {}}).execute({})
    assert not requests


@pytest.mark.parametrize("config", [
    {"operation": "get_customer", "id": "../42"},
    {"operation": "list_customers", "page_index": 0},
    {"operation": "list_products", "page_size": 101},
    {"operation": "create_product", "product": {"name": "Acme", "taxExcludedPrice": float('nan')}},
    {"operation": "create_customer", "customer": {"type": "Company"}},
    {"operation": "create_invoice", "invoice": {"date": "2026-02-30"}},
    {"operation": "update_customer", "id": 1, "customer": {"active": None}},
    {"operation": "create_invoice", "invoice": {"isDraft": False}},
])
def test_invalid_configs(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_connection_evidence_is_account_data_and_credential_is_manual():
    assert native.AltovizNode.connection_evidence.operation == "list_customers"
    schema = native.AltovizAPIKeyCredential.model_json_schema()
    assert schema["title"] == "Altoviz API Key"
    assert schema["properties"]["api_key"]["ui:widget"] == "password"
    assert len(native.OPERATIONS) == 25
