"""Creem factory, transport, validation and metadata projection tests."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
CID = "00000000-0000-4000-8000-000000000003"
WORKFLOW = "00000000-0000-4000-8000-000000000004"
FAMILY = "creem_api_key"
TOKEN = "synthetic_creem_api_key"
BLOB = {"environment": "test", "api_key": TOKEN}
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
PRODUCT, CUSTOMER, SUBSCRIPTION, LICENSE = "prod_fixture", "cust_fixture", "sub_fixture", "lic_fixture"
PRIVATE = "private_license_key_not_output"


@pytest.fixture
def ensure_native_db_pool():
    yield


def resource(rid, kind, **changes):
    return {"id": rid, "object": kind, "mode": "test", "created_at": "2026-10-06T00:00:00Z", "updated_at": "2026-10-06T00:00:00Z", **changes}


def product(**changes):
    return resource(PRODUCT, "product", **{"name": "Fixture product", "description": "Fixture description", "price": 400, "currency": "USD", "billing_type": "onetime", "status": "active", "checkout_url": "https://fixture.invalid/?token="+TOKEN, "features": [{"licenseKey": PRIVATE}], **changes})


def customer(**changes):
    return resource(CUSTOMER, "customer", **{"name": "Fixture customer", "external_id": "fixture-42", "country": "US", "email": "private@example.test", "metadata": {"private": TOKEN}, **changes})


def subscription(**changes):
    return resource(SUBSCRIPTION, "subscription", **{"product": PRODUCT, "customer": CUSTOMER, "status": "active", "last_transaction": {"amount": 400, "private": TOKEN}, **changes})


def license_metadata(**changes):
    return resource(LICENSE, "license", **{"product_id": PRODUCT, "status": "active", "activation": 1, "activation_limit": None, "expires_at": None, "key": PRIVATE, "instance": {"name": "private_device"}, **changes})


def page(items, requested=1, next_page=None):
    return {"items": items, "pagination": {"total_records": len(items)+(1 if next_page else 0), "total_pages": next_page or requested if items else 0, "current_page": requested, "next_page": next_page, "prev_page": requested-1 if requested>1 else None}}


@pytest.fixture
async def native(monkeypatch):
    from nodes import creem_node as provider
    from utils import ssrf
    state = SimpleNamespace(requests=[], replies={}, after_read=None, constructors=[])
    state.dns = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", state.dns)

    def respond(request):
        state.requests.append(request)
        if getattr(state, "transport_error", None):
            raise state.transport_error
        route = request.url.path.removeprefix("/v1/")
        reply = state.replies.get((request.method, route))
        if reply is None and request.method == "GET":
            current = int(request.url.params.get("page_number", "1"))
            if route == "products/search": reply = (200, page([product()], current))
            elif route == "products/"+PRODUCT: reply = (200, product())
            elif route == "customers": reply = (200, customer())
            elif route == "customers/list": reply = (200, page([customer()], current))
            elif route == "subscriptions": reply = (200, subscription())
            elif route in {"subscriptions/search", f"customers/{CUSTOMER}/subscriptions"}: reply = (200, page([subscription()], current))
            elif route == f"customers/{CUSTOMER}/orders": reply = (200, page([resource("ord_fixture", "order", product=PRODUCT, customer=CUSTOMER, status="paid", type="onetime", amount=400, transaction={"private": TOKEN})], current))
            elif route == f"customers/{CUSTOMER}/licenses": reply = (200, page([license_metadata()], current))
            elif route == f"licenses/{LICENSE}/instances": reply = (200, page([resource("inst_fixture", "license-instance", name="private_device", status="active")], current))
        assert reply is not None, (request.method, route)
        status, payload, *headers = reply
        content = b"" if payload is None else payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        response = httpx.Response(status, content=content, headers={"Content-Type": "application/json", **(headers[0] if headers else {})})
        if state.after_read:
            callback, state.after_read = state.after_read, None
            callback()
        return response

    original = ssrf.guarded_async_client
    def client(**kwargs):
        state.constructors.append(kwargs)
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(provider, "guarded_async_client", client)

    async def run(operation, args=None, *, blob=None):
        from nodes.core.registry import NodeFactory
        node = NodeFactory.create_node("fixture", "automation-creem", {
            "config": {"operation": operation, **(args or {})},
            "credentials": deepcopy(BLOB) if blob is None else blob,
        }, user_id=USER)
        return await node.execute({})
    state.run = run
    yield state


async def test_actual_factory_schema_tagless_connect_and_test_auth(native):
    from nodes.core.registry import NodeFactory
    from nodes.core.credential_connect import shape_credential, validate_for_connect
    from nodes.creem_node import CreemNode, CreemAPIKeyCredential
    shaped, errors, resolved = shape_credential(FAMILY, BLOB)
    assert not errors and shaped == BLOB and resolved[0] == "automation-creem"
    assert CreemAPIKeyCredential.model_validate(shaped).credential_type == FAMILY
    assert NodeFactory.is_registered("automation-creem")
    schema = CreemNode.get_config_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 15
    assert "name" in schema["$defs"]["CreateProduct"]["required"]
    assert "default" not in schema["$defs"]["CreateProduct"]["properties"]["name"]
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=BLOB, user_id=USER)
    assert verdict.ok
    req = native.requests[-1]
    assert req.url.host == "test-api.creem.io" and req.headers["x-api-key"] == TOKEN and "Authorization" not in req.headers
    assert dict(req.url.params) == {"page_number": "1", "page_size": "10"}
    assert all(c["trust_env"] is False and c["follow_redirects"] is False for c in native.constructors)


@pytest.mark.parametrize("tag", [None, "", 7, [], {}, "slack_oauth", " creem_api_key "])
def test_native_raw_family_refuses_before_inherited_reconciliation(native, tag):
    from nodes.creem_node import CreemNode
    from nodes.core.registry import NodeFactory
    from nodes.core.base import ConfigValidationError
    raw = {"config": {"operation": "list_products"}, "credentials": {**BLOB, "credential_type": tag}}
    assert CreemNode.validate_config(raw)["valid"] is False
    with pytest.raises(ConfigValidationError): NodeFactory.create_node("fixture", "automation-creem", raw, user_id=USER)
    assert native.requests == []










@pytest.mark.parametrize("operation,args", [("list_products", {"status": "archived", "page_number": 3}), ("get_product", {"product_id": PRODUCT}), ("list_customers", {}), ("get_customer", {"customer_id": CUSTOMER}), ("list_subscriptions", {}), ("get_subscription", {"customer_id": CUSTOMER, "subscription_id": SUBSCRIPTION}), ("list_customer_subscriptions", {"customer_id": CUSTOMER}), ("list_customer_orders", {"customer_id": CUSTOMER}), ("list_customer_licenses", {"customer_id": CUSTOMER}), ("list_license_instances", {"customer_id": CUSTOMER, "license_id": LICENSE, "license_page": 2})])
async def test_all_reads_native_routes_and_private_projection(native, operation, args):
    result = await native.run(operation, args)
    assert result["status"] == "success"
    for private in (TOKEN, PRIVATE, "private@example.test", "private_device", "checkout_url", "features", "last_transaction", '"amount"', '"metadata"'):
        assert private not in json.dumps(result)
    if operation == "get_subscription": assert dict(native.requests[-1].url.params) == {"subscription_id": SUBSCRIPTION}
    if operation == "list_license_instances":
        assert [r.url.path for r in native.requests] == ["/v1/customers", f"/v1/customers/{CUSTOMER}/licenses", f"/v1/licenses/{LICENSE}/instances"]
        assert dict(native.requests[-2].url.params) == {"page_number": "2", "page_size": "100"}


@pytest.mark.parametrize("failure", ["customer", "subscription", "license_membership"])
async def test_wrong_parent_or_absent_license_refuses_resource(native, failure):
    if failure == "customer":
        native.replies[("GET", "customers")] = (200, customer(id="cust_other"))
        operation, args = "list_customer_orders", {"customer_id": CUSTOMER}
    elif failure == "subscription":
        native.replies[("GET", "subscriptions")] = (200, subscription(customer="cust_other"))
        operation, args = "get_subscription", {"customer_id": CUSTOMER, "subscription_id": SUBSCRIPTION}
    else:
        native.replies[("GET", f"customers/{CUSTOMER}/licenses")] = (200, page([]))
        operation, args = "list_license_instances", {"customer_id": CUSTOMER, "license_id": LICENSE}
    result = await native.run(operation, args)
    assert result["status"] == "error"
    assert not any("/instances" in r.url.path for r in native.requests)
    if failure == "customer": assert len(native.requests) == 1


async def test_expanded_subscription_and_nullable_order_owner_are_documented(native):
    native.replies[("GET", "subscriptions")] = (200, subscription(customer=customer(), product=product()))
    assert (await native.run("get_subscription", {"customer_id": CUSTOMER, "subscription_id": SUBSCRIPTION}))["status"] == "success"
    native.replies[("GET", f"customers/{CUSTOMER}/orders")] = (200, page([resource("ord_fixture", "order", product=PRODUCT, status="pending", type="onetime")]))
    result = await native.run("list_customer_orders", {"customer_id": CUSTOMER})
    assert result["status"] == "success" and result["data"]["items"][0]["customer_id"] is None


@pytest.mark.parametrize("payload", [page([product(mode="prod")]), {"items": [], "pagination": {}}, {"items": [], "pagination": {"total_records": 0, "total_pages": 0, "current_page": True, "next_page": None, "prev_page": None}}, {"items": [], "pagination": {"total_records": 0, "total_pages": 0, "current_page": 1, "next_page": "https://evil.invalid", "prev_page": None}}, page([product(), product()]), {"status": 403, "error": "Forbidden", "message": [TOKEN]}, {"success": False}, [], b"unreadable"])
async def test_200_malformed_business_error_and_page_shapes_are_unverified(native, payload):
    native.replies[("GET", "products/search")] = (200, payload)
    result = await native.run("list_products")
    assert result["status"] == "error" and result.get("status_code") is None and TOKEN not in json.dumps(result)


@pytest.mark.parametrize("status", [201, 202, 204, 206, 302, 400, 401, 403, 404, 409, 429, 503])
async def test_exact_completion_status_and_safe_http_error_no_retry(native, status):
    native.replies[("GET", "products/search")] = (status, {"message": TOKEN}, {"Retry-After": "8"})
    result = await native.run("list_products")
    assert result["status"] == "error" and result["status_code"] == status and result["retry_after"] == 8
    assert len(native.requests) == 1 and TOKEN not in json.dumps(result)


async def test_create_update_archive_and_customer_wire_contracts(native):
    native.replies[("POST", "products")] = (200, product())
    result = await native.run("create_product", {"name": "Fixture product", "description": "Fixture description", "price": 400, "currency": "USD", "confirm_record_change": True})
    assert result["status"] == "success" and result["data"]["verified_readback"] is None
    assert json.loads(native.requests[-1].content) == {"name": "Fixture product", "description": "Fixture description", "price": 400, "currency": "USD", "tax_mode": "inclusive", "tax_category": "saas", "billing_type": "onetime", "abandoned_cart_recovery_enabled": False}
    native.replies[("PATCH", "products/"+PRODUCT)] = (200, product())
    assert (await native.run("update_product", {"product_id": PRODUCT, "clear_description": True, "confirm_record_change": True}))["status"] == "success"
    assert json.loads(native.requests[-1].content) == {"description": ""}
    native.replies[("DELETE", "products/"+PRODUCT)] = (200, product(status="archived"))
    assert (await native.run("archive_product", {"product_id": PRODUCT, "confirm_record_change": True}))["status"] == "success"
    native.replies[("DELETE", "products/"+PRODUCT)] = (204, None)
    assert (await native.run("archive_product", {"product_id": PRODUCT, "confirm_record_change": True}))["status"] == "error"
    native.replies[("POST", "customers")] = (200, customer())
    assert (await native.run("create_customer", {"name": "Fixture customer", "email": "fixture@example.test", "external_id": "fixture-42", "confirm_record_change": True}))["status"] == "success"
    assert json.loads(native.requests[-1].content) == {"name": "Fixture customer", "email": "fixture@example.test", "external_id": "fixture-42"}
    native.replies[("PATCH", "customers")] = (200, customer())
    assert (await native.run("update_customer", {"customer_id": CUSTOMER, "clear_external_id": True, "confirm_record_change": True}))["status"] == "success"
    assert json.loads(native.requests[-1].content) == {"customer_id": CUSTOMER, "external_id": None}


async def test_picker_bound_parent_search_environment_and_page_before_provider(native):
    from nodes.creem_node import CreemNode, freshen
    current = await freshen(BLOB)
    native.replies[("GET", f"customers/{CUSTOMER}/licenses")] = (200, page([license_metadata()], next_page=2))
    first = await CreemNode.load_field_options("license_id", current, {"customer_id": CUSTOMER}, search="lic_")
    assert first["options"] == [{"value": LICENSE, "label": LICENSE+" · active"}] and PRIVATE not in json.dumps(first)
    token = first["next_page_token"]; native.requests.clear()
    for context, blob, search in [({"customer_id": "cust_other"}, BLOB, "lic_"), ({"customer_id": CUSTOMER}, {**BLOB, "environment": "prod"}, "lic_"), ({"customer_id": CUSTOMER}, BLOB, "other")]:
        with pytest.raises(ValueError): await CreemNode.load_field_options("license_id", blob, context, token, search)
    with pytest.raises(ValueError): await CreemNode.load_field_options("license_id", BLOB, {})
    assert native.requests == []
    native.replies[("GET", f"customers/{CUSTOMER}/licenses")] = (200, page([license_metadata()], 2))
    await CreemNode.load_field_options("license_id", current, {"customer_id": CUSTOMER}, token, "lic_")
    assert native.requests[-1].url.params["page_number"] == "2"




@pytest.mark.parametrize("args", [{"price": 99}, {"price": True}, {"price": 1.5}, {"currency": "GBP"}, {"name": None}, {"confirm_record_change": False}, {"features": [{"type": "customerCredits"}]}])
async def test_write_invalid_fields_or_purchase_feature_never_probe(native, args):
    from nodes.core.base import ConfigValidationError
    values = {"name": "Fixture", "description": "Fixture", "price": 400, "currency": "USD", "confirm_record_change": True, **args}
    with pytest.raises(ConfigValidationError): await native.run("create_product", values)
    assert native.requests == []




async def test_empty_catalog_is_protected_access_without_synthetic_person_identity(native):
    from nodes.core.credential_connect import validate_for_connect
    native.replies[("GET", "products/search")] = (200, page([]))
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=BLOB, user_id=USER)
    assert verdict.ok
    assert len(native.requests) == 1 and native.requests[0].url.path == "/v1/products/search"




@pytest.mark.parametrize("member", ["product", "customer"])
async def test_expanded_subscription_members_cannot_cross_environments(native, member):
    raw = subscription()
    raw[member] = product(mode="prod") if member == "product" else customer(mode="prod")
    native.replies[("GET", "subscriptions")] = (200, raw)
    result = await native.run("get_subscription", {"customer_id": CUSTOMER, "subscription_id": SUBSCRIPTION})
    assert result["status"] == "error" and TOKEN not in json.dumps(result)
