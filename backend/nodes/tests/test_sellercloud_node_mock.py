"""Native factory tests against schema-shaped fixtures, without provider sign-ins."""
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from nodes import sellercloud_node as sc
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

FIXTURES = json.loads((Path(__file__).parent / "fixtures/sellercloud/responses.json").read_text())
AUTH = {"credential_type": "sellercloud_api_token", "api_base_url": "https://pbf2.api.sellercloud.com/rest", "api_token": "fixture-bearer-token"}


@pytest.fixture
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id="sellercloud-test", node_type="automation-sellercloud",
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    def handle(request):
        requests.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as session:
            yield session

    monkeypatch.setattr(sc, "guarded_async_client", client)
    return requests, replies


READS = [
    ("list_orders", {}, "/api/Orders"), ("get_order", {"order_id": 123}, "/api/Orders/123"),
    ("list_customers", {}, "/api/Customers"), ("get_customer", {"customer_id": 123}, "/api/Customers/123"),
    ("list_inventory", {}, "/api/Inventory"), ("get_inventory", {"product_id": "A/B ?"}, "/api/Inventory/Details"),
    ("list_companies", {}, "/api/Companies"), ("get_company", {"company_id": 1}, "/api/Companies/1"),
    ("list_warehouses", {}, "/api/Warehouses"), ("get_warehouse", {"warehouse_id": 1}, "/api/Warehouses/1"),
    ("list_vendors", {}, "/api/Vendors"), ("get_vendor", {"vendor_id": 1}, "/api/Vendors/1"),
    ("list_purchase_orders", {}, "/api/PurchaseOrders"), ("get_purchase_order", {"purchase_order_id": 1}, "/api/PurchaseOrders/1"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path", READS)
async def test_reads_use_exact_contract_routes(transport, operation, config, path):
    requests, replies = transport
    body = FIXTURES["orders"] if operation.startswith("list_") else {"ID": 123}
    replies.append((200, body))
    result = await node(operation, **config).execute({})
    req = requests[0]
    assert req.method == "GET" and req.url.path == "/rest" + path
    assert req.headers["Authorization"] == "Bearer fixture-bearer-token"
    assert result["data"] == body
    assert "fixture-bearer-token" not in json.dumps(result)
    if operation.startswith("list_"):
        assert dict(req.url.params) == {"model.pageNumber": "1", "model.pageSize": "100"}
        assert result["next_page_number"] is None
    if operation == "get_inventory":
        assert dict(req.url.params) == {"productID": "A/B ?"}


WRITES = [
    ("create_customer", {"first_name": "Test", "email": "test@example.test"}, "POST", "/api/Customers", {"FirstName": "Test", "Email": "test@example.test", "CustomerType": 1}),
    ("update_customer", {"customer_id": 4, "email": "new@example.test"}, "PUT", "/api/Customers/4", {"Email": "new@example.test"}),
    ("create_product", {"product_name": "Test", "product_sku": "SKU", "product_type_name": "Default"}, "POST", "/api/Products", {"ProductName": "Test", "ProductSKU": "SKU", "ProductTypeName": "Default"}),
    ("adjust_inventory", {"product_id": "SKU", "warehouse_id": 1, "quantity": 3, "adjustment_type": 0, "reason": "Damaged"}, "PUT", "/api/Inventory/AdjustPhysicalInventory", {"ProductID": "SKU", "WarehouseID": 1, "Qty": 3, "AdjustmentType": 0, "Reason": "Damaged"}),
    ("add_order_note", {"order_id": 7, "message": "Packed"}, "POST", "/api/Orders/7/Notes", {"Message": "Packed", "Category": 0, "IsPinned": False}),
    ("set_order_status", {"order_ids": [7], "status": 2}, "PUT", "/api/Orders/StatusCode", {"Orders": [7], "Status": 2}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,expected", WRITES)
async def test_writes_map_to_one_contract_operation(transport, operation, config, method, path, expected):
    requests, replies = transport
    replies.append((200, None))
    assert await node(operation, **config).execute({}) == {"data": None}
    assert len(requests) == 1
    assert requests[0].method == method and requests[0].url.path == "/rest" + path
    assert json.loads(requests[0].content) == expected


@pytest.mark.parametrize("url", ["http://pbf2.api.sellercloud.com/rest", "https://evil.test/rest", "https://pbf2.api.sellercloud.com.evil.test/rest", "https://user@pbf2.api.sellercloud.com/rest", "https://pbf2.api.sellercloud.com:443/rest", "https://127.0.0.1/rest", "https://pbf2.api.sellercloud.com/rest?x=1"])
def test_credential_refuses_foreign_or_ambiguous_hosts(url):
    with pytest.raises(ValueError):
        sc.SellerCloudTokenCredential.model_validate({**AUTH, "api_base_url": url})


def test_manual_credential_default_and_us_host():
    data = {k: v for k, v in AUTH.items() if k != "credential_type"}
    data["api_base_url"] = "https://test.api.sellercloud.us/rest/"
    result = sc.SellerCloudTokenCredential.model_validate(data)
    assert result.credential_type == "sellercloud_api_token"
    assert result.api_base_url == "https://test.api.sellercloud.us/rest"
    assert "fixture-bearer-token" not in repr(result)


@pytest.mark.asyncio
async def test_filters_and_pagination_preserve_wire_names(transport):
    requests, replies = transport
    replies.append((200, {"Items": [], "TotalResults": 300}))
    result = await node("list_orders", page_number=2, page_size=100, updated_from="11/01/2026 10:00").execute({})
    assert result["next_page_number"] == 3
    assert dict(requests[0].url.params) == {"model.pageNumber": "2", "model.pageSize": "100", "model.lastUpdatedFrom": "11/01/2026 10:00"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_errors_are_not_success_and_no_write_retry(transport, status):
    requests, replies = transport
    replies.append((status, {"Message": "Rejected fixture-bearer-token"}))
    with pytest.raises(ValueError, match=f"SellerCloud HTTP {status}") as exc:
        await node("add_order_note", order_id=1, message="Test").execute({})
    assert "fixture-bearer-token" not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"Items": {}}, {"Items": [], "TotalResults": "1"}, {"Items": [1], "TotalResults": 1}])
async def test_malformed_lists_are_not_connection_evidence(transport, body):
    transport[1].append((200, body))
    with pytest.raises(ValueError):
        await node("list_companies").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,version", [("order", "LastUpdated"), ("inventory", "LastModifiedDate")])
async def test_poll_baselines_emits_edits_and_rebaselines_scope(transport, kind, version):
    requests, replies = transport
    operation = "on_new_or_updated_" + kind
    n = node(operation)
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    n._update_node_state = update
    fixture = deepcopy(FIXTURES["orders" if kind == "order" else "inventory"])
    for _ in range(2):
        replies.append((200, fixture))
        assert (await n.execute({}))["items"] == []
    changed = deepcopy(fixture)
    changed["Items"][0][version] = "2026-11-09T13:00:00Z"
    replies.append((200, changed))
    output = await n.execute({})
    assert output["new_item_count"] == 1
    event = sc.SellerCloudNode.resolve_agent_event(output)
    assert str(changed["Items"][0]["ID"]) in event["text"]
    assert "get_order" in event["text"] if kind == "order" else "get_inventory" in event["text"]
    other = node(operation, updated_from="11/09/2026 12:30")
    other._update_node_state = update
    replies.append((200, changed))
    assert (await other.execute({}))["items"] == []
    assert requests[-1].url.params["model.lastUpdatedFrom"] == "11/09/2026 12:30"
    assert poll_scope(sc.SellerCloudNode, {"operation": operation}) == poll_scope(sc.SellerCloudNode, {"operation": operation, "label": "Cosmetic"})


@pytest.mark.asyncio
async def test_poll_reads_all_pages_before_dedup_and_fails_incomplete(transport):
    n = node("on_new_or_updated_order")
    state = {"seen_ids": []}
    async def update(mutator, **kwargs):
        new_state, result = mutator(state.copy())
        if new_state is not None:
            state.update(new_state)
        return result
    n._update_node_state = update
    first = deepcopy(FIXTURES["orders"])
    first["TotalResults"] = 201
    second = deepcopy(FIXTURES["orders"])
    second["TotalResults"] = 201
    second["Items"][0]["ID"] = 456
    transport[1].extend([(200, first), (200, second)])
    result = await n.execute({})
    assert result["new_item_count"] == 2
    assert [r.url.params["model.pageNumber"] for r in transport[0]] == ["1", "2"]
    transport[1].append((200, {"Items": [], "TotalResults": 201}))
    previous = deepcopy(state)
    with pytest.raises(ValueError, match="incomplete"):
        await n.execute({})
    assert state == previous


@pytest.mark.asyncio
async def test_connect_evidence_shows_account_companies(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport[1].append((200, FIXTURES["companies"]))
    result = await collect_evidence(node_type="automation-sellercloud", pool=None, user_id="test", credential_data=AUTH)
    assert result.reachable is True
    assert result.samples[0].label == "Test Company"
    assert transport[0][0].url.path == "/rest/api/Companies"


@pytest.mark.asyncio
async def test_create_order_sends_required_nested_details(transport):
    requests, replies = transport
    replies.append((200, 123))
    await node("create_order", company_id=1, customer_email="test@example.test", first_name="Test", last_name="Customer",
        address="123 Test Street", city="Test City", zip_code="10001", country="US", source_order_id="EXT-1",
        products=[{"product_id": "SKU", "quantity": 2, "unit_price": 12.5, "warehouse_id": 4}]).execute({})
    assert requests[0].method == "POST" and requests[0].url.path == "/rest/api/Orders"
    assert json.loads(requests[0].content) == {
        "CustomerDetails": {"Email": "test@example.test", "FirstName": "Test", "LastName": "Customer"},
        "OrderDetails": {"CompanyID": 1, "OrderSourceOrderID": "EXT-1"},
        "ShippingAddress": {"FirstName": "Test", "LastName": "Customer", "Address": "123 Test Street", "City": "Test City", "ZipCode": "10001", "Country": "US"},
        "Products": [{"ProductID": "SKU", "Qty": 2, "SitePrice": 12.5, "ShipFromWareHouseID": 4}]}


@pytest.mark.asyncio
async def test_create_purchase_order_uses_unit_quantity_mode(transport):
    requests, replies = transport
    replies.append((200, 123))
    await node("create_purchase_order", company_id=1, vendor_id=2,
        products=[{"product_id": "SKU", "quantity": 3, "unit_price": 5.0}]).execute({})
    assert requests[0].method == "POST" and requests[0].url.path == "/rest/api/PurchaseOrders"
    assert json.loads(requests[0].content) == {"CompanyID": 1, "VendorID": 2, "POType": 0, "CaseQtyMode": False,
        "Products": [{"ProductID": "SKU", "QtyUnitsOrdered": 3, "UnitPrice": 5.0}]}


@pytest.mark.asyncio
async def test_update_shipping_sends_tracking_to_exact_endpoint(transport):
    requests, replies = transport
    replies.append((200, None))
    await node("update_shipping_status", order_id=1, shipping_carrier="UPS", shipping_service="Ground", tracking_number="TEST123").execute({})
    assert requests[0].method == "PUT" and requests[0].url.path == "/rest/api/Orders/ShippingStatus"
    assert json.loads(requests[0].content) == {"OrderID": 1, "ShippingCarrier": "UPS", "ShippingService": "Ground", "TrackingNumber": "TEST123"}
