"""Synthetic wire regressions for Commerce Layer's pinned JSON:API contract."""
import json
from urllib.parse import urlencode

import httpx
import pytest
from pydantic import ValidationError
from nodes import commerce_layer_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-commerce-layer-token"
ID = "XAyRWNUzyN"
CREDENTIAL = {"credential_type": "commerce_layer_access_token", "organization_slug": "shop-test", "access_token": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="commerce-layer-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, body=None, status=200, reply=None):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if reply else httpx.Response(status, json=body, headers={"Content-Type": native.MEDIA})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def record(kind, identifier=ID):
    return {"id": identifier, "type": kind, "attributes": {"name": "Test product", "code": "TSHIRTMM000000FFFFFFXLXX", "email": "john@example.com", "quantity": 4, "amount_cents": 10000, "reference": "ERP-123", "password": "private", "jwt": TOKEN}}


CASES = [
    ({"operation": "create_order", "market_id": ID, "customer_email": "john@example.com"}, {"customer_email": "john@example.com"}, {"market": "markets"}),
    ({"operation": "update_order", "order_id": ID, "reference": "ERP-123", "coupon_code": "SUMMERDISCOUNT"}, {"reference": "ERP-123", "coupon_code": "SUMMERDISCOUNT"}, {}),
    ({"operation": "create_customer", "email": "john@example.com"}, {"email": "john@example.com"}, {}),
    ({"operation": "update_customer", "customer_id": ID, "email": "john@example.com"}, {"email": "john@example.com"}, {}),
    ({"operation": "create_sku", "code": "TSHIRTMM000000FFFFFFXLXX", "name": "T-shirt", "shipping_category_id": ID}, {"code": "TSHIRTMM000000FFFFFFXLXX", "name": "T-shirt"}, {"shipping_category": "shipping_categories"}),
    ({"operation": "update_sku", "sku_id": ID, "name": "T-shirt", "description": ""}, {"name": "T-shirt"}, {}),
    ({"operation": "create_price", "sku_id": ID, "price_list_id": ID, "amount_cents": 0}, {"amount_cents": 0}, {"sku": "skus", "price_list": "price_lists"}),
    ({"operation": "update_price", "price_id": ID, "amount_cents": 10000}, {"amount_cents": 10000}, {}),
    ({"operation": "update_stock_item", "stock_item_id": ID, "quantity": 0}, {"quantity": 0}, {}),
    ({"operation": "create_line_item", "order_id": ID, "sku_code": "TSHIRTMM000000FFFFFFXLXX", "quantity": 4}, {"sku_code": "TSHIRTMM000000FFFFFFXLXX", "quantity": 4}, {"order": "orders"}),
    ({"operation": "update_line_item", "line_item_id": ID, "quantity": 4}, {"quantity": 4}, {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,attributes,relations", CASES)
async def test_typed_writes_exact_wire_and_one_request(monkeypatch, config, attributes, relations):
    method, kind = native.OPERATIONS[config["operation"]]
    requests = transport(monkeypatch, {"data": record(kind)}, status=201 if method == "POST" else 200)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["item"]["id"] == ID
    assert TOKEN not in str(result) and "private" not in str(result) and "jwt" not in str(result)
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "shop-test.commercelayer.io" and request.method == method
    assert request.url.path == "/api/" + kind + ("/" + ID if method == "PATCH" else "")
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Content-Type"] == native.MEDIA and request.headers["Accept"] == native.MEDIA
    data = {"type": kind, "attributes": attributes}
    if method == "PATCH":
        data["id"] = ID
    if relations:
        data["relationships"] = {k: {"data": {"type": v, "id": ID}} for k, v in relations.items()}
    assert json.loads(request.content) == {"data": data}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [n for n in native.OPERATIONS if n.startswith(("get_", "list_"))])
async def test_all_reads_paths_and_explicit_pagination(monkeypatch, operation):
    _, kind = native.OPERATIONS[operation]
    cfg = {"operation": operation}
    is_list = operation.startswith("list_")
    if not is_list:
        cfg[operation.removeprefix("get_") + "_id"] = ID
    body = {"data": [record(kind)] if is_list else record(kind)}
    if is_list:
        cfg.update(page_number=3, page_size=5)
        body["links"] = {"next": "https://shop-test.commercelayer.io/api/" + kind + "?" + urlencode({"page[number]": 4, "page[size]": 5})}
    requests = transport(monkeypatch, body)
    result = await node(cfg).run({})
    assert result["status"] == "success" and len(requests) == 1
    assert requests[0].url.path == "/api/" + kind + ("" if is_list else "/" + ID)
    if is_list:
        assert dict(requests[0].url.params) == {"page[number]": "3", "page[size]": "5"}
        assert result["next_page_number"] == 4 and result["has_more"] and not result["complete"]


@pytest.mark.asyncio
async def test_delete_204_never_parses_body(monkeypatch):
    requests = transport(monkeypatch, status=204)
    result = await node({"operation": "delete_line_item", "line_item_id": ID}).execute({})
    assert result["deletion_acknowledged"] and result["deleted_id"] == ID
    assert requests[0].method == "DELETE" and not requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 422, 429, 500])
async def test_errors_keep_provider_reason_redact_token_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"errors": [{"detail": "Not allowed: " + TOKEN}]}, status)
    with pytest.raises(ValueError, match="Not allowed: \\[redacted\\]"):
        await node({"operation": "create_customer", "email": "john@example.com"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"errors": []}, {"data": {}}, {"data": {"id": ID, "type": "orders", "attributes": {}}}, {"data": record("skus", "different")}])
async def test_invalid_or_different_resource_cannot_succeed(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "get_sku", "sku_id": ID}).execute({})


@pytest.mark.asyncio
async def test_pagination_unknown_empty_terminal_and_foreign_link(monkeypatch):
    transport(monkeypatch, {"data": []})
    result = await node({"operation": "list_skus"}).execute({})
    assert result["has_more"] is None and not result["complete"]
    transport(monkeypatch, {"data": [], "links": {"next": None}})
    result = await node({"operation": "list_skus"}).execute({})
    assert result["complete"] and result["has_more"] is False
    requests = transport(monkeypatch, {"data": [], "links": {"next": "https://evil.example/api/skus?page[number]=2&page[size]=10"}})
    with pytest.raises(ValueError, match="pagination"):
        await node({"operation": "list_skus"}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("slug", ["https://evil.example", "https://shop.commercelayer.io.evil.example", "https://evil@shop.commercelayer.io", "https://shop.commercelayer.io:443", "../auth", "auth", "http://shop.commercelayer.io"])
def test_host_boundary(slug):
    with pytest.raises(ValidationError):
        native.CommerceLayerAccessToken.model_validate({**CREDENTIAL, "organization_slug": slug})


def test_credential_shaping_registry_and_evidence():
    assert NODE_REGISTRY[native.NODE_TYPE] is native.CommerceLayerNode
    assert native.CommerceLayerNode.connection_evidence.operation == "list_skus"
    shaped = native.CommerceLayerAccessToken.model_validate({**CREDENTIAL, "organization_slug": " https://shop-test.commercelayer.io/admin ", "access_token": " " + TOKEN + " "})
    assert shaped.organization_slug == "shop-test" and shaped.access_token == TOKEN
    for token in ["Bearer abc", "https://example.com/key", "abc\nvalue", "abc\x00value"]:
        with pytest.raises(ValidationError):
            native.CommerceLayerAccessToken.model_validate({**CREDENTIAL, "access_token": token})


@pytest.mark.parametrize("config", [{"operation": "get_sku", "sku_id": "../customers"}, {"operation": "list_skus", "page_size": 26}, {"operation": "create_order"}, {"operation": "create_price", "amount_cents": 100}, {"operation": "create_customer", "email": "john@example.com", "password": "bad"}])
def test_invalid_configuration_is_rejected_before_http(config):
    with pytest.raises(ValueError):
        node(config)


def test_other_credential_family_is_rejected():
    wrong = {**CREDENTIAL, "credential_type": "unrelated_token"}
    with pytest.raises(ValueError, match="Commerce Layer"):
        node({"operation": "list_skus"}, wrong)
    assert not native.CommerceLayerNode.validate_config({"config": {"operation": "list_skus"}, "credentials": wrong})["valid"]


@pytest.mark.asyncio
async def test_provider_documented_sku_response(monkeypatch):
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / "fixtures/commerce-layer/sku-retrieve.json").read_text())
    transport(monkeypatch, fixture["body"])
    result = await node({"operation": "get_sku", "sku_id": fixture["body"]["data"]["id"]}).execute({})
    assert result["item"]["code"] == "TSHIRTMM000000FFFFFFXLXX"
    assert result["item"]["name"] == "Men's Black T-shirt with White Logo (XL)"


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture_name,config", [
    ("price-retrieve", {"operation": "get_price", "price_id": ID}),
    ("line-item-update", {"operation": "update_line_item", "line_item_id": ID, "quantity": 4}),
])
async def test_documented_rule_outcomes_array_is_accepted(monkeypatch, fixture_name, config):
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / "fixtures/commerce-layer" / (fixture_name + ".json")).read_text())
    assert fixture["body"]["data"]["attributes"]["rule_outcomes"] == []
    transport(monkeypatch, fixture["body"])
    result = await node(config).execute({})
    assert result["item"]["id"] == ID and result["status"] == "success"
