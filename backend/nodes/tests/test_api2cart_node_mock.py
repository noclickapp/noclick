"""Actual native factory/wire/projection fixtures; synthetic literals, UNRUN."""
import asyncio
from copy import deepcopy
import json
import logging
import httpx
import pytest
from nodes import api2cart_node as v
from nodes.core.registry import NodeFactory

SECRET = "synthetic-api2cart-account-key"
STORE_SECRET = "synthetic-api2cart-store-key"
CRED = {"credential_type": v.FAMILY, "api_key": SECRET, "store_key": STORE_SECRET,
        "platform_id": "Shopify", "store_id": "1"}
ROWS = {
    "products": {"id": "p-owned", "name": "Owned product", "u_model": "owned-model", "u_sku": "", "price": 0,
                 "description": "Owned description", "stores_ids": ["1"], "avail_sale": False, "avail_view": False},
    "categories": {"id": "c-owned", "name": "Owned category", "description": "Owned category description", "parent_id": "", "stores_ids": ["1"], "avail": False},
    "customers": {"id": "customer-owned", "status": "enabled", "is_guest": False, "stores_ids": ["1"], "email": SECRET, "first_name": SECRET, "address": {"secret": SECRET}},
    "orders": {"id": "order-owned", "order_id": "ORDER-FIXTURE", "store_id": "1", "status": {"id": "draft", "name": "Draft", "history": [SECRET]}, "total": 42, "customer": {"email": SECRET}, "payment_method": SECRET},
}


def envelope(result, **extras):
    return httpx.Response(200, json={"return_code": 0, "return_message": SECRET, "result": result, **extras})


@pytest.fixture
def ensure_native_db_pool():
    yield


class Fixture:
    def __init__(self):
        self.requests, self.rows, self.deleted, self.override = [], deepcopy(ROWS), set(), None

    async def send(self, request):
        self.requests.append(request)
        assert request.url.host == "api.api2cart.com" and request.url.scheme == "https"
        assert request.headers["x-api-key"] == SECRET
        assert SECRET not in str(request.url) and STORE_SECRET not in str(request.url)
        name = request.url.path.removeprefix("/v1.1/").removesuffix(".json")
        assert name in v.ROUTES and request.method == v.ROUTES[name]
        if name != "account.cart.list": assert request.headers["x-store-key"] == STORE_SECRET
        else: assert "x-store-key" not in request.headers
        if self.override:
            result = self.override(request)
            if result is not None: return result
        if name == "account.cart.list":
            return envelope({"carts_count": 1, "carts": [{"id": "connection-owned", "store_key": STORE_SECRET,
                "cart_id": "Shopify", "custom_label": "Owned fixture", "url": "https://private.example.test/" + SECRET}]})
        if name == "cart.info":
            return envelope({"name": "Shopify", "url": SECRET, "owner": {"email": SECRET},
                "stores_info": [{"store_id": "1", "name": "Owned store", "language": "en", "timezone": "UTC", "active": True, "root_category_id": ""}]})
        if name == "cart.methods": return envelope({"method": sorted(v.ROUTES)})
        singular, action = name.split(".")
        kind = next(kind for kind, value in v.KINDS.items() if value[0] == singular)
        row = self.rows[kind]
        if action == "list":
            if "page_cursor" in request.url.params: assert set(request.url.params) == {"page_cursor"}
            else: assert request.url.params["store_id"] == "1" and "response_fields" in request.url.params
            return envelope({singular: [] if kind in self.deleted else [row], v.KINDS[kind][1]: None}, pagination={"next": None, "previous": None})
        if action == "info":
            assert request.url.params["id"] == row["id"] and request.url.params["store_id"] == "1"
            if kind in self.deleted: return httpx.Response(200, json={"return_code": 112, "return_message": SECRET, "result": {}})
            return envelope(row)
        if action == "delete":
            self.deleted.add(kind)
            return envelope({"delete_items": 1 if kind == "products" else True})
        assert action in {"add", "update"} and kind in {"products", "categories"}
        body = json.loads(request.content) if kind == "products" else dict(request.url.params)
        assert body["store_id"] == "1"
        if kind == "categories": assert not request.content
        if action == "add":
            if kind == "products":
                assert body["available_for_sale"] is False and body["available_for_view"] is False
                assert {"name", "model", "description", "price"} <= set(body)
                row.update(u_model=body["model"], avail_sale=False, avail_view=False)
            else: assert body["avail"] == "false"
        row.update({k: value for k, value in body.items() if k in {"name", "description", "price", "parent_id"}})
        return envelope({singular + "_id": row["id"]} if action == "add" else {"updated_items": 1})


@pytest.fixture
def native(monkeypatch):
    state = Fixture(); original = httpx.AsyncClient
    monkeypatch.setattr(v.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(state.send), **kw))
    return state


def node(operation, **config):
    return NodeFactory.create_node(node_id="api2cart-fixture", node_type=v.TYPE,
        node_data={"config": {"operation": operation, **config}, "credentials": deepcopy(CRED)})


CASES = [("test_connection", {}), ("get_store", {}), ("list_stores", {}), ("list_supported_methods", {}),
    ("list_products", {}), ("get_product", {"product_id": "p-owned"}),
    ("create_product", {"confirm_disposable": True, "name": "New fixture", "model": "new-model", "description": "New\nfixture", "price": 0}),
    ("update_product", {"confirm_disposable": True, "product_id": "p-owned", "name": "Updated fixture"}),
    ("delete_product", {"confirm_disposable": True, "product_id": "p-owned"}),
    ("list_categories", {}), ("get_category", {"category_id": "c-owned"}),
    ("create_category", {"confirm_disposable": True, "name": "New category"}),
    ("update_category", {"confirm_disposable": True, "category_id": "c-owned", "description": "Updated category"}),
    ("delete_category", {"confirm_disposable": True, "category_id": "c-owned"}),
    ("list_customers", {}), ("get_customer", {"customer_id": "customer-owned"}),
    ("list_orders", {}), ("get_order", {"order_id": "order-owned"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config", CASES)
async def test_all_eighteen_native_factory_branches_exact_wire_and_private_projection(native, operation, config):
    assert {operation for operation, _ in CASES} == set(v.OPERATIONS)
    result = await node(operation, **config).execute({})
    assert result["status"] == "success" and result["action"] == operation
    assert SECRET not in json.dumps(result) and STORE_SECRET not in json.dumps(result)
    assert [r.url.path for r in native.requests[:3]] == ["/v1.1/account.cart.list.json", "/v1.1/cart.info.json", "/v1.1/cart.methods.json"]
    if operation == "test_connection": assert result["data"]["identity_verified"] is False
    if operation.startswith(("create_", "update_", "delete_")):
        mutation = next(i for i, r in enumerate(native.requests) if r.method != "GET")
        assert any(r.url.path.endswith(".info.json") for r in native.requests[mutation + 1:])


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["account", "platform", "store", "method"])
async def test_protected_association_store_or_capability_denial_before_resource(native, scope):
    def override(r):
        if scope in {"account", "platform"} and r.url.path.endswith("account.cart.list.json"):
            return envelope({"carts_count": 1, "carts": [{"id": "x", "store_key": STORE_SECRET if scope == "platform" else "foreign", "cart_id": "Magento"}]})
        if scope == "store" and r.url.path.endswith("cart.info.json"): return envelope({"stores_info": [{"store_id": "foreign"}]})
        if scope == "method" and r.url.path.endswith("cart.methods.json"): return envelope({"method": ["cart.info"]})
    native.override = override
    with pytest.raises(ValueError): await node("list_products").execute({})
    assert not any(r.url.path.endswith("product.list.json") for r in native.requests)


@pytest.mark.asyncio
async def test_cursor_only_wire_and_repeated_stateful_cursor_are_not_fabricated_or_retried(native):
    native.override = lambda r: envelope({"product": [ROWS["products"]], "products_count": None},
        pagination={"next": "constant%2Fopaque-provider-cursor", "previous": None}) if r.url.path.endswith("product.list.json") else None
    first = await node("list_products", page_size=1).execute({})
    token = first["data"]["next_page_token"]
    second = await node("list_products", page_size=1, page_token=token).execute({})
    assert second["data"]["next_page_token"] == token and second["data"]["count"] is None
    assert dict(native.requests[-1].url.params) == {"page_cursor": "constant%2Fopaque-provider-cursor"}
    for changed in ({"store_id": "2"}, {"platform_id": "Magento"}, {"api_key": "foreign"}, {"store_key": "foreign"}):
        with pytest.raises(ValueError): v._cursor({**CRED, **changed}, {"operation": "list_products", "page_size": 1, "page_token": token, "category_id": None})
    before = len(native.requests)
    with pytest.raises(ValueError): await node("list_products", page_size=2, page_token=token).execute({})
    assert len(native.requests) == before


@pytest.mark.asyncio
async def test_category_filter_is_verified_and_restricted_to_initial_page(native):
    await node("list_products", category_id="c-owned").execute({})
    assert any(r.url.path.endswith("category.info.json") for r in native.requests)
    assert native.requests[-1].url.params["category_id"] == "c-owned"


@pytest.mark.asyncio
@pytest.mark.parametrize("membership", [[], ["foreign"], None])
async def test_resource_without_exact_parent_membership_is_not_projected(native, membership):
    native.rows["products"]["stores_ids"] = membership
    with pytest.raises(ValueError, match="store"): await node("list_products").execute({})


@pytest.mark.asyncio
async def test_metadata_response_size_is_bounded_without_retry(native):
    native.override = lambda _r: httpx.Response(200, content=b" " * (v.MAX_BYTES + 1), headers={"content-type": "application/json"})
    with pytest.raises(ValueError, match="metadata limit"): await node("test_connection").execute({})
    assert len(native.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config", [case for case in CASES if case[0].startswith(("create_", "update_", "delete_"))])
async def test_catalog_confirmation_precedes_any_io(native, operation, config):
    with pytest.raises(ValueError, match="confirmation"): await node(operation, **{**config, "confirm_disposable": False}).execute({})
    assert not native.requests


@pytest.mark.asyncio
async def test_unknown_or_visible_metadata_refuses_update_before_mutation(native):
    native.rows["products"].pop("avail_view")
    with pytest.raises(ValueError, match="hidden"): await node("update_product", confirm_disposable=True, product_id="p-owned", name="Updated").execute({})
    assert all(r.method == "GET" for r in native.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["scope112", "target403", "target0"])
async def test_delete_readback_never_treats_scope_or_permission_error_as_absence(native, failure):
    def override(r):
        if "products" not in native.deleted: return None
        if failure == "scope112" and r.url.path.endswith("account.cart.list.json"):
            return httpx.Response(200, json={"return_code": 112, "return_message": SECRET})
        if r.url.path.endswith("product.info.json"):
            return httpx.Response(403, json={"error": SECRET}) if failure == "target403" else envelope(ROWS["products"])
    native.override = override
    with pytest.raises(ValueError): await node("delete_product", confirm_disposable=True, product_id="p-owned").execute({})
    assert sum(r.method == "DELETE" for r in native.requests) == 1


@pytest.mark.asyncio
async def test_create_separate_readback_model_or_visibility_failure_is_not_retried(native):
    native.override = lambda r: envelope({**native.rows["products"], "u_model": "wrong"}) if r.url.path.endswith("product.info.json") else None
    with pytest.raises(ValueError, match="readback differs"):
        await node("create_product", confirm_disposable=True, name="New", model="exact-model", description="New", price=0).execute({})
    assert sum(r.method == "POST" for r in native.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(429, text=SECRET), httpx.Response(302, headers={"location": "https://foreign.test/" + SECRET}),
    httpx.Response(200, json={"return_code": 109, "return_message": SECRET}), httpx.Response(200, json={"return_code": True, "result": {}}),
    httpx.Response(200, text=SECRET), httpx.Response(204), httpx.Response(200, content=b"{broken", headers={"content-type": "application/json"})])
async def test_exact_errors_are_safe_and_not_retried(native, response):
    native.override = lambda _r: response
    with pytest.raises(ValueError) as caught: await node("test_connection").execute({})
    assert SECRET not in str(caught.value) and len(native.requests) == 1


def test_literal_foreign_family_and_closed_dispatch():
    raw = {"config": {"operation": "test_connection"}, "credentials": {**CRED, "credential_type": "foreign"}}
    assert v.API2CartNode.validate_config(raw)["valid"] is False
    with pytest.raises(ValueError): NodeFactory.create_node(node_id="fixture", node_type=v.TYPE, node_data=raw)
    with pytest.raises(ValueError): node("account.cart.add")


@pytest.mark.asyncio
async def test_scoped_http_log_filter_preserves_concurrent_unrelated_diagnostics():
    logger = logging.getLogger("httpx"); old = logger.level; logger.setLevel(logging.INFO)
    messages, inside, release = [], asyncio.Event(), asyncio.Event()
    class Sink(logging.Handler):
        def emit(self, record): messages.append(record.getMessage())
    handler = Sink();logger.addHandler(handler)
    async def native_request():
        with v._private_http():
            inside.set(); await release.wait(); logger.info("Native key=%s", SECRET)
    async def unrelated():
        await inside.wait();logger.info("Unrelated request completed");release.set()
    try: await asyncio.gather(native_request(), unrelated())
    finally: logger.removeHandler(handler);logger.setLevel(old)
    assert messages == ["Unrelated request completed", "API2Cart HTTP exchange; details omitted"]
    assert SECRET not in str(messages)
