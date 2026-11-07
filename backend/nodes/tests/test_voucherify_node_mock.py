"""Prepared, unrun real factory/run/connect/evidence/socket regressions.

Only storage/encryption/public DNS/HTTP boundaries are synthetic. These are
source fixtures, not provider account, policy-database or business-action proof.
"""
from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation
from nodes import voucherify_node as native

NODE, FAMILY = native.NODE_TYPE, "voucherify_application_keys"
CID, USER, ORG, OWNER, WORKFLOW = (str(UUID(int=i)) for i in (42, 1, 3, 2, 4))
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
CREDS = {"credential_type": FAMILY, "region": "eu", "application_id": "synthetic-app-id-42", "application_secret": "synthetic-app-secret-42"}
OPS = {"list_customers", "get_customer", "create_customer", "update_customer", "delete_customer", "list_products", "get_product", "create_product", "update_product", "delete_product", "list_skus", "get_sku", "create_sku", "update_sku", "delete_sku", "list_campaigns", "get_campaign", "update_campaign_metadata", "list_vouchers", "get_voucher", "update_voucher_metadata", "list_promotion_tiers", "get_promotion_tier", "validate_discounts"}
ROWS = {
    "customer": {"id": "cust_ONE", "source_id": "external-one", "name": "Fixture customer", "email": "fixture@example.invalid", "phone": "private-phone", "address": {"line_1": "private-address"}, "metadata": {"private": "private-custom"}},
    "product": {"id": "prod_ONE", "name": "Fixture product", "price": 999, "image_url": "https://private.invalid/image", "metadata": {"private": "private-custom"}},
    "sku": {"id": "sku_ONE", "product_id": "prod_ONE", "sku": "Fixture SKU", "price": 999, "currency": "USD", "metadata": {"private": "private-custom"}},
    "campaign": {"id": "camp_ONE", "name": "Fixture campaign", "campaign_type": "DISCOUNT_COUPONS", "active": False, "voucher": {"gift": {"balance": 999}}, "metadata": {"private": "private-custom"}},
    "voucher": {"id": "v_ONE", "code": "SUMMER42", "campaign_id": "camp_ONE", "type": "DISCOUNT_VOUCHER", "active": False, "assets": {"qr": {"url": "private-asset"}}, "holder_id": "private-holder", "gift": {"balance": 999}, "metadata": {"private": "private-custom"}},
    "promotion_tier": {"id": "promo_ONE", "name": "Fixture tier", "campaign_id": None, "campaign": {"id": "camp_ONE"}, "hierarchy": 0, "active": False, "action": {"discount": {"amount_off": 999}}, "metadata": {"private": "private-custom"}},
}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def provider(monkeypatch):
    state = SimpleNamespace(requests=[], records={key: [deepcopy(row)] for key, row in ROWS.items()}, override=None, status=None, raw=None, headers={}, after_response=None, timeout=False)
    original_client = httpx.AsyncClient
    async def respond(request):
        assert request.url.scheme == "https" and request.url.host in {"api.voucherify.io", "us1.api.voucherify.io", "as1.api.voucherify.io"}
        assert request.headers["x-app-id"] == CREDS["application_id"] and request.headers["x-app-token"] == CREDS["application_secret"]
        assert request.headers["x-voucherify-api-version"] == "v2018-08-01" and request.headers["accept"] == "application/json"
        assert "authorization" not in request.headers and all(v not in str(request.url) for v in (CREDS["application_id"], CREDS["application_secret"]))
        state.requests.append(request)
        if state.timeout:
            raise httpx.ReadTimeout("private body " + CREDS["application_secret"], request=request)
        parts = request.url.path.split("/")
        assert parts[:2] == ["", "v1"]
        group = parts[2]
        resource = {"customers": "customer", "products": "product", "skus": "sku", "campaigns": "campaign", "vouchers": "voucher", "promotions": "promotion_tier", "validations": "validation"}[group]
        listed = len(parts) == 3 and request.method == "GET"
        if group == "products" and len(parts) >= 5:
            resource, listed = "sku", len(parts) == 5 and request.method == "GET"
        if group == "promotions":
            listed = len(parts) == 5 and parts[-1] == "tiers"
            if listed:
                assert not request.url.params
        if resource == "validation":
            assert request.method == "POST" and parts == ["", "v1", "validations"]
            body = json.loads(request.content)
            assert "session" not in body and "options" not in body
            value = {"id": "valid_ONE", "valid": False, "redeemables": [{"object": r["object"], "id": r["id"], "status": "INAPPLICABLE", "result": {"error": {"code": 400, "key": "validation_rules_violated", "message": "private-custom-rule"}}, "metadata": {"private": "private-custom"}} for r in body["redeemables"]], "tracking_id": "private-tracking", "stacking_rules": {"private": "private-config"}}
        elif listed:
            field = {"customer": "customers", "product": "products", "sku": "skus", "campaign": "campaigns", "voucher": "vouchers", "promotion_tier": "tiers"}[resource]
            value = {"object": "list", "data_ref": "data" if resource == "sku" else field, field: deepcopy(state.records[resource]), "total": len(state.records[resource])}
        else:
            value = deepcopy(state.records[resource][0])
        if request.method == "DELETE":
            assert resource in ("customer", "product", "sku")
            if resource != "customer":
                assert request.url.params["force"] == "false"
        if request.method in ("PUT", "POST") and resource != "validation":
            body = json.loads(request.content)
            assert not set(body) & {"price", "currency", "discount", "gift", "loyalty_card", "active", "image_url", "id"}
        if state.after_response:
            state.after_response()
        if state.override is not None:
            value = state.override(request, value) if callable(state.override) else deepcopy(state.override)
        status = (204 if request.method == "DELETE" else 200) if state.status is None else state.status
        if state.raw is not None:
            return httpx.Response(status, content=state.raw, headers={"content-type": "application/json", **state.headers})
        if request.method == "DELETE":
            return httpx.Response(status, content=b"", headers=state.headers)
        return httpx.Response(status, json=value, headers={"content-type": "application/json", **state.headers})
    def client(**kwargs):
        assert kwargs == {"follow_redirects": False, "trust_env": False, "timeout": 25.0}
        return original_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return state


async def run(operation, arguments=None, **kwargs):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=arguments or {}, user_id=USER, credential_data=kwargs.pop("credential_data", CREDS), **kwargs)


def test_actual_factory_catalog_and_explicit_server_key_family():
    from coder.workflow.operation_catalog import get_operations_for_node_type, node_accepted_credential_types
    assert NODE_REGISTRY[NODE] is native.VoucherifyNode
    assert node_accepted_credential_types(NODE) == {FAMILY}
    assert {op.name for op in get_operations_for_node_type(NODE)} == OPS
    node = NodeFactory.create_node("fixture", NODE, {"config": {"operation": "list_campaigns"}, "credentials": CREDS}, user_id=USER)
    assert isinstance(node, native.VoucherifyNode)
    assert "synthetic-app" not in repr(native.VoucherifyApplicationKeysCredential.model_validate(CREDS))


@pytest.mark.parametrize("field,value", [("credential_type", None), ("credential_type", "voucherify_client_keys"), ("region", "http://localhost"), ("region", "dedicated"), ("application_id", "YOUR_APP_ID"), ("application_secret", "https://private.invalid/key"), ("application_secret", "synthetic\nsecret"), ("application_id", "abc def")])
def test_native_family_region_and_secret_guards(field, value):
    with pytest.raises(ValueError) as error:
        native._credential({**CREDS, field: value})
    assert str(value) not in str(error.value)


CASES = [
    ("list_customers", {}, "GET", "/v1/customers"), ("get_customer", {"customer_id": "cust_ONE"}, "GET", "/v1/customers/cust_ONE"),
    ("create_customer", {"customer": {"name": "Fixture", "source_id": "external-one"}}, "POST", "/v1/customers"), ("update_customer", {"customer_id": "cust_ONE", "customer": {"name": "Fixture"}}, "PUT", "/v1/customers/cust_ONE"), ("delete_customer", {"customer_id": "cust_ONE", "confirm_delete": True}, "DELETE", "/v1/customers/cust_ONE"),
    ("list_products", {}, "GET", "/v1/products"), ("get_product", {"product_id": "prod_ONE"}, "GET", "/v1/products/prod_ONE"), ("create_product", {"product": {"name": "Fixture"}}, "POST", "/v1/products"), ("update_product", {"product_id": "prod_ONE", "product": {"name": "Fixture"}}, "PUT", "/v1/products/prod_ONE"), ("delete_product", {"product_id": "prod_ONE", "confirm_delete": True, "confirm_cascade_skus": True}, "DELETE", "/v1/products/prod_ONE"),
    ("list_skus", {"product_id": "prod_ONE"}, "GET", "/v1/products/prod_ONE/skus"), ("get_sku", {"product_id": "prod_ONE", "sku_id": "sku_ONE"}, "GET", "/v1/skus/sku_ONE"), ("create_sku", {"product_id": "prod_ONE", "sku": {"sku": "Fixture"}}, "POST", "/v1/products/prod_ONE/skus"), ("update_sku", {"product_id": "prod_ONE", "sku_id": "sku_ONE", "sku": {"sku": "Fixture"}}, "PUT", "/v1/products/prod_ONE/skus/sku_ONE"), ("delete_sku", {"product_id": "prod_ONE", "sku_id": "sku_ONE", "confirm_delete": True}, "DELETE", "/v1/products/prod_ONE/skus/sku_ONE"),
    ("list_campaigns", {}, "GET", "/v1/campaigns"), ("get_campaign", {"campaign_id": "camp_ONE"}, "GET", "/v1/campaigns/camp_ONE"), ("update_campaign_metadata", {"campaign_id": "camp_ONE", "metadata": {"fixture": False}}, "PUT", "/v1/campaigns/camp_ONE"),
    ("list_vouchers", {"campaign_id": "camp_ONE"}, "GET", "/v1/vouchers"), ("get_voucher", {"campaign_id": "camp_ONE", "voucher_code": "SUMMER42"}, "GET", "/v1/vouchers/SUMMER42"), ("update_voucher_metadata", {"campaign_id": "camp_ONE", "voucher_code": "SUMMER42", "metadata": {"fixture": 0}}, "PUT", "/v1/vouchers/SUMMER42"),
    ("list_promotion_tiers", {"campaign_id": "camp_ONE"}, "GET", "/v1/promotions/camp_ONE/tiers"), ("get_promotion_tier", {"campaign_id": "camp_ONE", "promotion_tier_id": "promo_ONE"}, "GET", "/v1/promotions/tiers/promo_ONE"), ("validate_discounts", {"redeemables": [{"object": "voucher", "id": "SUMMER42", "campaign_id": "camp_ONE"}, {"object": "promotion_tier", "id": "promo_ONE", "campaign_id": "camp_ONE"}], "order_amount": 1000, "customer_id": "cust_ONE"}, "POST", "/v1/validations"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,method,path", CASES)
async def test_native_contracts_and_minimal_projection(provider, op, args, method, path):
    result = await run(op, args)
    assert result["status"] == "success" and provider.requests[-1].method == method and provider.requests[-1].url.path == path
    assert "private-" not in json.dumps(result) and CREDS["application_secret"] not in json.dumps(result)
    if op == "validate_discounts":
        assert result["data"]["valid"] is False and result["data"]["redemption_performed"] is False
        assert result["data"]["redeemables"][0]["error"] == {"code": 400, "key": "validation_rules_violated"}
    elif method in ("POST", "PUT"):
        assert result["data"]["acknowledged"] is True and result["data"]["readback_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args", [("get_product", {"product_id": "../private"}), ("list_customers", {"page": 100}), ("list_vouchers", {"campaign_id": "camp_ONE", "page": 100}), ("list_products", {"limit": 101}), ("delete_sku", {"sku_id": "sku_ONE", "product_id": "prod_ONE", "confirm_delete": 1}), ("create_product", {"product": {"name": "Fixture", "price": 100}}), ("update_campaign_metadata", {"campaign_id": "camp_ONE", "metadata": {"x": {"private": "nested"}}}), ("redeem", {}), ("create_voucher", {}), ("validate_discounts", {"redeemables": [{"object": "gift", "id": "gift_ONE", "campaign_id": "camp_ONE"}]})])
async def test_invalid_undeclared_and_effectful_inputs_refused_before_http(provider, op, args):
    with pytest.raises(ValueError):
        await run(op, args)
    assert provider.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("resource,op,args,parent", [("sku", "update_sku", {"product_id": "prod_ONE", "sku_id": "sku_ONE", "sku": {"sku": "Fixture"}}, "product_id"), ("voucher", "update_voucher_metadata", {"campaign_id": "camp_ONE", "voucher_code": "SUMMER42", "metadata": {"x": False}}, "campaign_id"), ("promotion_tier", "get_promotion_tier", {"campaign_id": "camp_ONE", "promotion_tier_id": "promo_ONE"}, "campaign_id")])
async def test_parent_associations_refused_before_mutation(provider, resource, op, args, parent):
    provider.records[resource][0][parent] = "foreign_PARENT"
    with pytest.raises(ValueError, match="requested"):
        await run(op, args)
    assert all(r.method == "GET" for r in provider.requests)


@pytest.mark.asyncio
async def test_product_delete_requires_explicit_cascade_confirmation(provider):
    with pytest.raises(ValueError):
        await run("delete_product", {"product_id": "prod_ONE", "confirm_delete": True})
    assert provider.requests == []
    result = (await run("delete_product", {"product_id": "prod_ONE", "confirm_delete": True, "confirm_cascade_skus": True}))["data"]
    assert result["moved_to_bin"] is True and result["related_skus_affected"] is True
    assert result["permanent_deletion"] is False and result["absence_verified"] is False


@pytest.mark.asyncio
async def test_page_boundary_preserves_unknown_more_and_false_metadata(provider):
    row = ROWS["campaign"]
    provider.records["campaign"] = [{**row, "id": "camp_" + str(i)} for i in range(2)]
    result = (await run("list_campaigns", {"limit": 2, "page": 100}))["data"]
    assert result["has_more"] is None and result["next_page"] is None and result["page_cap_reached"] is True
    assert result["items"][0]["active"] is False
    provider.override = lambda _request, raw: {**raw, "has_more": False}
    assert (await run("list_campaigns", {"limit": 2}))["data"]["has_more"] is False


@pytest.mark.asyncio
async def test_optional_provider_total_is_unknown_but_required_total_is_checked(provider):
    provider.override = lambda _request, raw: {key: value for key, value in raw.items() if key != "total"}
    result = (await run("list_campaigns"))["data"]
    assert result["total"] is None and result["returned_count"] == 1
    with pytest.raises(ValueError, match="collection"):
        await run("list_customers")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 402, 403, 404, 409, 423, 429, 500])
async def test_errors_remain_private_and_not_retried(provider, status):
    provider.status, provider.raw = status, ("private-response " + CREDS["application_secret"]).encode()
    with pytest.raises(ValueError) as error:
        await run("list_campaigns")
    assert len(provider.requests) == 1 and "private-response" not in str(error.value) and CREDS["application_secret"] not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b'{"code":401,"message":"private-key"}', b'{"object":"list","object":"list"}', b'{"total":NaN}', b'[]', b'{"object":"list","data_ref":"campaigns","campaigns":[],"total":"0"}'])
async def test_http200_provider_errors_and_invalid_envelopes(provider, raw):
    provider.raw = raw
    with pytest.raises(ValueError):
        await run("list_campaigns")
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_media_bounds_transport_logging_and_secret_echo(provider, caplog):
    caplog.set_level(logging.DEBUG)
    provider.timeout = True
    with pytest.raises(ValueError, match="could not complete"):
        await run("list_campaigns")
    assert "synthetic-app" not in caplog.text
    provider.timeout, provider.headers = False, {"content-type": "text/html"}
    with pytest.raises(ValueError, match="format"):
        await run("list_campaigns")
    provider.headers, provider.raw = {}, b"x" * (native.MAX_BYTES + 1)
    with pytest.raises(ValueError, match="bounded"):
        await run("list_campaigns")
    provider.raw = None
    provider.records["campaign"][0]["name"] = CREDS["application_secret"]
    with pytest.raises(ValueError, match="credential material"):
        await run("list_campaigns")


@pytest.mark.asyncio
async def test_exact_code_encoding_and_validation_response_binding(provider):
    provider.records["voucher"][0]["code"] = "SUMMER +5"
    await run("get_voucher", {"campaign_id": "camp_ONE", "voucher_code": "SUMMER +5"})
    assert provider.requests[-1].url.raw_path == b"/v1/vouchers/SUMMER%20%2B5"
    provider.records["voucher"][0]["code"] = "SUMMER42"
    provider.override = lambda request, raw: {**raw, "redeemables": [{"object": "voucher", "id": "UNREQUESTED", "status": "APPLICABLE", "result": {}}]} if request.url.path == "/v1/validations" else raw
    with pytest.raises(ValueError, match="different"):
        await run("validate_discounts", {"redeemables": [{"object": "voucher", "id": "SUMMER42", "campaign_id": "camp_ONE"}]})


