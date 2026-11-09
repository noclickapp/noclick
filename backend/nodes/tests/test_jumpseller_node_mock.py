"""Jumpseller single-request contract and failure regressions (offline)."""
import base64
import json
from pathlib import Path
import httpx
import pytest
from nodes import jumpseller_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/jumpseller/requests.json").read_text())["cases"]
CREDENTIAL = {"credential_type": "jumpseller_api_key", "login": "synthetic-api-login", "authtoken": "synthetic-auth-token"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="jumpseller-test", node_type="automation-jumpseller",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, response, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        return httpx.Response(status, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_all_operations_exact_request_and_documented_envelopes(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "api.jumpseller.com"
    assert request.method == case["method"] and request.url.path == case["path"]
    assert dict(request.url.params) == case["params"]
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"synthetic-api-login:synthetic-auth-token").decode()
    assert request.headers["Content-Type"] == "application/json"
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert "should-not-leak" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_rejections_preserve_provider_message_without_secrets_or_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Permission denied: synthetic-auth-token"}, status)
    result = await node({"operation": "list_products"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["message"] == "Permission denied: [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"product": {"id": 456}}, {"product": {"id": True}}, {"error": "bad"}])
async def test_malformed_and_foreign_detail_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "get_product", "product_id": 123}).execute({})
    assert result["status"] == "error" and "data" not in result


@pytest.mark.asyncio
async def test_one_page_and_search_totals(monkeypatch):
    transport(monkeypatch, [{"product": {"id": 123}}])
    out = await node({"operation": "list_products", "page": 2, "limit": 1}).execute({})
    assert out["has_more"] and out["next_page"] == 3
    transport(monkeypatch, {"count": 1, "customers": [{"id": 123}]})
    out = await node({"operation": "search_customers", "query": "example", "limit": 1}).execute({})
    assert out["items"] == [{"id": 123}] and not out["has_more"]


@pytest.mark.asyncio
async def test_writes_fail_ambiguously_without_retry_and_strip_secret_fields(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("synthetic-auth-token"))
    out = await node({"operation": "update_stock", "location_id": 1, "product_id": 2, "stock": 0, "stock_unlimited": False}).execute({})
    assert out["status"] == "unknown" and len(requests) == 1
    assert CREDENTIAL["authtoken"] not in str(out)
    transport(monkeypatch, {"customer": {"id": 123, "password": "private", "email": "customer@example.com"}})
    out = await node({"operation": "get_customer", "customer_id": 123}).execute({})
    assert out["data"] == {"id": 123, "email": "customer@example.com"}


@pytest.mark.parametrize("config", [
    {"operation": "get_product", "product_id": "../customers"},
    {"operation": "list_products", "limit": 101},
    {"operation": "update_customer", "customer_id": 123},
    {"operation": "create_product", "name": "Example"},
    {"operation": "list_categories", "url": "https://other.example"},
    {"operation": "update_order", "order_id": 123, "status": "invented"},
])
def test_invalid_configs_fail_before_network(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credentials_default_type_and_clean_secret():
    assert native.JumpsellerAPICredential(login="api-login", authtoken="auth-token").credential_type == native.CREDENTIAL_TYPE
    with pytest.raises(ValueError):
        native.JumpsellerAPICredential(login="https://example.com", authtoken="auth-token")
    assert len(CASES) == len(native.ROUTES) == 24
