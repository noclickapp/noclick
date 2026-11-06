"""Test all actions with provider-authored responses and real HTTP serialization.

Every fixture records its exact source URL, drawn from the official sources:
https://github.com/bigcommerce/api-specs/tree/dcf48407308710b882374ffafbeefdb0b3598abe/reference
https://docs.bigcommerce.com/developer/api-reference/rest/admin/management/inventory
"""
import json
from pathlib import Path
from unittest.mock import Mock
import httpx
import pytest
from pydantic import ValidationError
from nodes.bigcommerce_node import (
    BigCommerceAPITokenCredential,
    BigCommerceNode,
    BigCommerceNodeConfig,
)

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/bigcommerce/responses.json").read_text()
)
TOKEN = "bigcommerce-test-secret"
CLIENT = httpx.AsyncClient


def node(config):
    return BigCommerceNode(
        node_id="test",
        node_type="automation-bigcommerce",
        node_data={},
        config=BigCommerceNodeConfig(
            config=config,
            credentials=BigCommerceAPITokenCredential(
                store_hash="abc123", access_token=TOKEN
            ),
        ),
        sio=Mock(),
    )


def transport(monkeypatch, callback):
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: CLIENT(
            transport=httpx.MockTransport(callback), trust_env=False
        ),
    )


def expected_payload(op, c):
    if op == "create_order":
        return json.loads(c["order_json"])
    if op == "update_order":
        return {"status_id": c["status_id"]}
    if op == "create_shipment":
        return {
            k: c[k]
            for k in ["order_address_id", "tracking_number", "shipping_provider"]
        } | {"items": json.loads(c["items_json"])}
    if op == "create_product":
        return {k: c[k] for k in ["name", "type", "weight", "price", "sku"]} | {
            "categories": []
        }
    if op == "update_product":
        return {k: c[k] for k in ["name", "type", "weight", "price", "is_visible"]}
    if op in ["create_customers", "update_customers"]:
        return json.loads(c["customers_json"])
    if op in ["set_inventory", "adjust_inventory"]:
        return {"items": json.loads(c["items_json"]), "reason": c["reason"]}
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_documented_operation(operation, monkeypatch):
    f = FIXTURES[operation]
    c = f["config"]
    seen = []

    def answer(req):
        seen.append(req)
        assert req.method == f["method"]
        assert req.url.host == "api.bigcommerce.com"
        assert req.url.path == f["path"].format(
            store_hash="abc123", **{k: v for k, v in c.items() if k.endswith("_id")}
        )
        assert req.headers["X-Auth-Token"] == TOKEN
        assert req.headers["Accept"] == "application/json"
        assert req.headers["Content-Type"] == "application/json"
        payload = expected_payload(operation, c)
        if payload is not None:
            assert json.loads(req.content) == payload
        else:
            assert req.content == b""
        query = {"page": "1", "limit": "5"} if operation.startswith("list_") else {}
        if operation == "list_products":
            query["sku"] = "SM-13"
        if operation == "list_customers":
            query["email:in"] = "string@example.com"
        if operation in ["list_inventory", "list_location_inventory"]:
            query["sku:in"] = "RE-130"
        if operation == "delete_customers":
            query = {"id:in": "1"}
        assert dict(req.url.params) == query
        return httpx.Response(
            f["status_code"], **({"json": f["body"]} if f["status_code"] != 204 else {})
        )

    transport(monkeypatch, answer)
    result = await node(c).execute({})
    assert len(seen) == 1
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["status_code"] == f["status_code"]
    assert result["data"] == (
        f["body"] if f["status_code"] != 204 else {"success": True}
    )
    assert set(result["timing_ms"]) == {"total", "api_request"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500])
async def test_error_redaction(monkeypatch, status):
    transport(
        monkeypatch,
        lambda req: httpx.Response(status, json={"title": f"Rejected {TOKEN}"}),
    )
    result = await node({"operation": "get_store"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert result["error"] == "Rejected [redacted]"
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_empty_products(monkeypatch):
    transport(
        monkeypatch, lambda req: httpx.Response(200, json={"data": [], "meta": {}})
    )
    assert (await node({"operation": "list_products"}).execute({}))[
        "status"
    ] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list_products", "get_store"])
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"message": "Invalid token"},
        {"data": {}},
        {"success": False},
        {"errors": {"name": "Invalid"}},
    ],
)
async def test_evidence_rejects_false_success(monkeypatch, operation, body):
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    assert (await node({"operation": operation}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_evidence_rejects_html(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, text="<html>Sign in</html>"))
    assert (await node({"operation": "get_store"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception", [httpx.ReadTimeout("secret"), httpx.ConnectError("secret")]
)
async def test_transport_errors(monkeypatch, exception):
    def fail(req):
        raise exception

    transport(monkeypatch, fail)
    result = await node({"operation": "get_store"}).execute({})
    assert result["status"] == "error" and "secret" not in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [
        {"operation": "delete_customers", "customer_ids": "1&email=x"},
        {"operation": "create_customers", "customers_json": "{}"},
        {"operation": "create_customers", "customers_json": '[{"first_name":"Jane"}]'},
        {
            "operation": "update_customers",
            "customers_json": '[{"email":"jane@example.com"}]',
        },
        {"operation": "create_order", "order_json": "not json"},
        {"operation": "create_order", "order_json": '{"products":[]}'},
        {"operation": "update_product", "product_id": 1},
        {"operation": "update_order", "order_id": 1},
        {
            "operation": "create_shipment",
            "order_id": 1,
            "order_address_id": 1,
            "items_json": '[{"quantity":1}]',
        },
        {
            "operation": "set_inventory",
            "items_json": '[{"location_id":1,"variant_id":74,"quantity":-1}]',
        },
        {
            "operation": "adjust_inventory",
            "items_json": '[{"location_id":1,"quantity":1}]',
        },
        {
            "operation": "set_inventory",
            "items_json": '[{"location_id":1,"quantity":1,"sku":"RE-130","variant_id":1}]',
        },
    ],
)
async def test_invalid_writes_never_send(config, monkeypatch):
    def fail(req):
        pytest.fail("Invalid input made an HTTP request")

    transport(monkeypatch, fail)
    with pytest.raises(ValueError):
        await node(config).execute({})


@pytest.mark.parametrize(
    "store_hash",
    [
        "https://api.bigcommerce.com/stores/abc123",
        "abc/123",
        "abc?x=1",
        "..",
        "ABC123",
        "",
    ],
)
def test_store_hash_validation(store_hash):
    with pytest.raises(ValidationError):
        BigCommerceAPITokenCredential(store_hash=store_hash, access_token=TOKEN)


@pytest.mark.asyncio
async def test_zero_and_false_preserved(monkeypatch):
    def answer(req):
        assert json.loads(req.content) == {
            "name": "1L Le Parfait Jar",
            "type": "physical",
            "weight": 1.0,
            "price": 0.0,
            "is_visible": False,
        }
        return httpx.Response(200, json=FIXTURES["update_product"]["body"])

    transport(monkeypatch, answer)
    assert (
        await node(
            {
                "operation": "update_product",
                "product_id": 174,
                "name": "1L Le Parfait Jar",
                "type": "physical",
                "weight": 1,
                "price": 0,
                "is_visible": False,
            }
        ).execute({})
    )["status"] == "success"


@pytest.mark.asyncio
async def test_missing_credentials():
    n = BigCommerceNode(
        node_id="test",
        node_type="automation-bigcommerce",
        node_data={},
        config=BigCommerceNodeConfig(config={"operation": "list_products"}),
        sio=Mock(),
    )
    with pytest.raises(ValueError, match="Connect your BigCommerce"):
        await n.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_collect_connection_evidence(monkeypatch, empty):
    from nodes.core.connection_evidence import collect_evidence

    paths = []

    def answer(req):
        paths.append(req.url.path)
        if req.url.path.endswith("/products"):
            return httpx.Response(
                200, json={"data": []} if empty else FIXTURES["list_products"]["body"]
            )
        return httpx.Response(200, json=FIXTURES["get_store"]["body"])

    transport(monkeypatch, answer)
    result = await collect_evidence(
        node_type="automation-bigcommerce",
        user_id="test",
        credential_data={
            "credential_type": "bigcommerce_api_token",
            "store_hash": "abc123",
            "access_token": TOKEN,
        },
    )
    assert result.reachable is True
    if empty:
        assert result.account_label == "BigCommerce"
        assert paths == [
            "/stores/abc123/v3/catalog/products",
            "/stores/abc123/v2/store",
        ]
    else:
        assert result.samples
        assert paths == ["/stores/abc123/v3/catalog/products"]


@pytest.mark.asyncio
async def test_inventory_filters(monkeypatch):
    def answer(req):
        assert dict(req.url.params) == {
            "page": "2",
            "limit": "10",
            "variant_id:in": "79",
            "location_id:in": "1",
        }
        return httpx.Response(200, json=FIXTURES["list_inventory"]["body"])

    transport(monkeypatch, answer)
    result = await node(
        {
            "operation": "list_inventory",
            "variant_id": 79,
            "location_id": 1,
            "page": 2,
            "limit": 10,
        }
    ).execute({})
    assert result["status"] == "success"
