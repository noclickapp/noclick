"""Exercise Magento's native discovery, typed configuration and REST request/output behavior.

Synthetic responses isolate network calls; expected routes and payloads are independent
of the implementation and match Adobe's published 2.4.8 contract.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import magento_v2_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-magento-token-42"
CREDENTIAL = {"credential_type": "magento_v2_access_token", "api_base_url": "https://store.example.com/shop/rest/default", "access_token": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/magento-v2/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="magento-fixture", node_type="automation-magento-v2",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, payload, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c["config"]["operation"] for c in CASES])
async def test_magento_v2_all_operations_native_factory_contract(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).run({})
    assert result["success"] is True
    assert result["data"] == case["response"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == "/shop/rest/default" + case["path"]
    assert request.url.host == "store.example.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == case.get("params", {})
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_magento_v2_search_paging_filter_and_sort_are_exact(monkeypatch):
    requests = transport(monkeypatch, {"items": [{"sku": "24-MB01", "name": "Joust Duffle Bag"}], "total_count": 5})
    config = {"operation": "list_products", "current_page": 2, "page_size": 2,
        "filter_field": "sku", "filter_value": "24-% +", "condition_type": "like", "sort_field": "updated_at", "sort_direction": "DESC"}
    result = await node(config).execute({})
    assert dict(requests[0].url.params) == {"searchCriteria[pageSize]": "2", "searchCriteria[currentPage]": "2",
        "searchCriteria[filterGroups][0][filters][0][field]": "sku", "searchCriteria[filterGroups][0][filters][0][value]": "24-% +",
        "searchCriteria[filterGroups][0][filters][0][conditionType]": "like", "searchCriteria[sortOrders][0][field]": "updated_at", "searchCriteria[sortOrders][0][direction]": "DESC"}
    assert result["pagination"] == {"current_page": 2, "page_size": 2, "total_count": 5, "has_more": True, "next_page": 3}
    transport(monkeypatch, {"items": [], "total_count": 0})
    result = await node({"operation": "list_products"}).execute({})
    assert result["pagination"]["has_more"] is False


@pytest.mark.asyncio
async def test_magento_v2_sku_is_one_encoded_component(monkeypatch):
    requests = transport(monkeypatch, {"sku": "SKU /?%#é"})
    await node({"operation": "get_product", "sku": "SKU /?%#é"}).execute({})
    assert requests[0].url.raw_path == b"/shop/rest/default/V1/products/SKU%20%2F%3F%25%23%C3%A9"
    assert not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["delete_product", "cancel_order", "hold_order", "unhold_order", "add_order_comment"])
async def test_magento_v2_false_acknowledgement_is_not_success(monkeypatch, operation):
    transport(monkeypatch, False)
    case = next(c for c in CASES if c["config"]["operation"] == operation)
    result = await node(case["config"]).execute({})
    assert result["success"] is False and result["status"] == "error"
    assert result["acknowledged"] is False


@pytest.mark.asyncio
async def test_magento_v2_provider_rejection_redacts_token(monkeypatch):
    transport(monkeypatch, {"message": "The consumer isn't authorized: " + TOKEN}, 401)
    result = await node({"operation": "list_products"}).execute({})
    assert result["success"] is False and result["http_status"] == 401
    assert result["message"] == "The consumer isn't authorized: [redacted]"
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"items": {}}, {"items": [1], "total_count": 1}, {"items": [], "total_count": -1}])
async def test_magento_v2_malformed_page_is_not_connection_proof(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "list_products"}).execute({})


@pytest.mark.parametrize("root", ["http://store.example.com/rest/default", "https://store.example.com", "https://user:pass@store.example.com/rest/default",
    "https://store.example.com/rest/default?token=x", "https://store.example.com/rest/default#x", "https://store.example.com/rest/../default",
    "https://store.example.com/rest/%2e%2e", "https://store.example.com:444/rest/default"])
def test_magento_v2_refuses_unsafe_or_incomplete_roots(root):
    with pytest.raises(ValidationError):
        native.MagentoV2TokenCredential.model_validate({**CREDENTIAL, "api_base_url": root})


def test_magento_v2_hand_connect_default_and_normalization():
    parsed = native.MagentoV2TokenCredential.model_validate({"api_base_url": " https://STORE.example.com/rest/default/ ", "access_token": TOKEN})
    assert parsed.credential_type == "magento_v2_access_token"
    assert parsed.api_base_url == "https://store.example.com/rest/default"
    assert native.MagentoV2Node.connection_evidence.operation == "list_products"


@pytest.mark.parametrize("config", [{"operation": "list_products", "filter_field": "sku"}, {"operation": "list_products", "page_size": 101},
    {"operation": "get_order", "order_id": 0}, {"operation": "update_product", "sku": "SKU"},
    {"operation": "get_product", "sku": ".."}, {"operation": "get_product", "sku": "x", "url": "https://bad.example.com"}])
def test_magento_v2_invalid_config_is_rejected_before_network(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_magento_v2_adobe_documented_product_response(monkeypatch):
    documented = json.loads((Path(__file__).parent / "fixtures/magento-v2/product.json").read_text())
    transport(monkeypatch, documented)
    result = await node({"operation": "get_product", "sku": "MS-Champ-S"}).execute({})
    assert result["data"] == documented
    assert result["data"]["extension_attributes"]["stock_item"]["low_stock_date"] is None
    assert result["data"]["name"] == "Champ Tee Small"


@pytest.mark.asyncio
async def test_magento_v2_ssrf_guard_refuses_destination_before_send(monkeypatch):
    import utils.ssrf as ssrf
    async def refuse(url):
        raise ssrf.SSRFError("Private address refused")
    monkeypatch.setattr(ssrf, "assert_url_allowed", refuse)
    with pytest.raises(ValueError, match="could not complete"):
        await node({"operation": "list_products"}).execute({})
