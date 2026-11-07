"""SkuVault factory, operation, connect and parser regressions with mocked HTTP."""
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
from nodes.core.credential_connect import validate_for_connect
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation
from nodes import skuvault_node as native

NODE, FAMILY = native.NODE_TYPE, "skuvault_api_tokens"
CID, USER, ORG, OWNER, WORKFLOW = (str(UUID(int=i)) for i in (42, 1, 3, 2, 4))
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
CREDS = {"credential_type": FAMILY, "tenant_token": "synthetic-tenant-42", "user_token": "synthetic-user-42"}
WINDOW = {"modified_after_utc": "2026-10-01T00:00:00Z", "modified_before_utc": "2026-10-06T00:00:00Z"}
OPS = {"list_external_warehouses", "list_warehouses", "list_locations", "list_products", "get_product", "list_kits", "list_brands", "list_classifications", "list_inventory_by_location", "list_item_quantities", "list_available_quantities", "list_kit_quantities", "list_warehouse_item_quantities", "get_warehouse_item_quantity", "list_external_warehouse_quantities", "create_product", "update_product"}
ARGS = {"get_product": {"sku": "sku-42"}, "list_kits": WINDOW, "list_warehouse_item_quantities": {"warehouse_id": 42}, "get_warehouse_item_quantity": {"warehouse_id": 42, "sku": "sku-42"}, "list_external_warehouse_quantities": {"warehouse_id": 43}, "create_product": {"sku": "sku-42", "classification": "Fixture class", "supplier": "Fixture supplier", "brand": "Fixture brand"}, "update_product": {"sku": "sku-42", "clear_description": True}}
PRODUCT = {"Id": "42", "Sku": "sku-42", "Description": "Fixture product", "Code": "code-42", "IsAlternateSKU": False, "QuantityOnHand": 0, "Cost": 99, "SalePrice": 99, "Attributes": [{"Value": "private-custom"}], "PictureUrl": "private-download"}
RESPONSES = {
    "inventory/getExternalWarehouses": {"Warehouses": [{"Id": "43", "Code": "external-42", "Name": "Fixture external"}]},
    "inventory/getWarehouses": {"Warehouses": [{"Id": "42", "Code": "regular-42"}]},
    "inventory/getLocations": {"Items": [{"WarehouseCode": "regular-42", "WarehouseName": "Fixture regular", "LocationCode": "location-42", "TotalQuantity": 0}], "Status": "OK"},
    "products/getProducts": {"Products": [PRODUCT]}, "products/getProduct": {"Product": PRODUCT},
    "products/getKits": {"Kits": [{"SKU": "kit-42", "Description": "Fixture kit", "AvailableQuantity": 0, "Cost": 99, "KitLines": [{"LineName": "line-42", "Quantity": 1, "Combine": 1, "Items": [{"SKU": "sku-42"}]}]}]},
    "products/getBrands": {"Brands": [{"Name": "Fixture brand", "IsEnabled": False}]},
    "products/getClassifications": {"Classifications": [{"Name": "Fixture class", "IsEnabled": True, "Attributes": [{"Value": "private-custom"}]}]},
    "inventory/getInventoryByLocation": {"Items": {"sku-42": [{"LocationCode": "location-42", "WarehouseCode": "regular-42", "Quantity": -1, "Reserve": False}]}},
    "inventory/getItemQuantities": {"Items": [{"Sku": "sku-42", "Code": "code-42", "AvailableQuantity": 0, "TotalOnHand": -1}]},
    "inventory/getAvailableQuantities": {"Items": [{"Sku": "sku-42", "AvailableQuantity": 0, "IsAlternateSku": False}]},
    "inventory/getKitQuantities": {"Kits": [{"Sku": "kit-42", "AvailableQuantity": 0}]},
    "inventory/getWarehouseItemQuantities": {"ItemQuantities": [{"Sku": "sku-42", "Quantity": 0}]},
    "inventory/getWarehouseItemQuantity": {"TotalQuantityOnHand": 0},
    "inventory/getExternalWarehouseQuantities": {"Quantities": [{"Sku": "sku-42", "InStockQuantity": 0, "TotalQuantity": -1}]},
    "products/createProduct": {"Status": "OK"}, "products/updateProduct": {"Status": "OK"},
}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def provider(monkeypatch):
    from utils import ssrf
    state = SimpleNamespace(requests=[], records=deepcopy(RESPONSES), override=None, status=200, raw=None, headers={}, after_response=None, timeout=False, dns_refused=False)
    original_dns, original_client = ssrf._resolve_host_addresses, ssrf.guarded_async_client
    async def public_dns(host, port, **kwargs):
        assert kwargs.get("permit_non_public", False) is False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            assert host == "app.skuvault.com"
            if state.dns_refused:
                raise ssrf.SSRFError("Synthetic DNS policy refusal")
            return ["93.184.216.34"]
        return await original_dns(host, port, **kwargs)
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", public_dns)
    async def respond(request):
        assert request.method == "POST" and request.url.scheme == "https" and request.url.host == "app.skuvault.com"
        route = request.url.path.removeprefix("/api/")
        assert route in RESPONSES and request.url.query == b"" and "authorization" not in request.headers
        assert request.headers["accept"] == "application/json" and request.headers["content-type"] == "application/json"
        body = json.loads(request.content)
        assert body["TenantToken"] == CREDS["tenant_token"] and body["UserToken"] == CREDS["user_token"]
        assert all(secret not in str(request.url) + str(request.headers) for secret in (CREDS["tenant_token"], CREDS["user_token"]))
        state.requests.append(request)
        if state.timeout:
            raise httpx.ReadTimeout("private body " + CREDS["user_token"], request=request)
        envelope = {"Errors": [], **deepcopy(state.records[route])}
        if state.after_response:
            state.after_response()
        if state.override is not None:
            envelope = state.override(request, envelope) if callable(state.override) else deepcopy(state.override)
        if state.raw is not None:
            return httpx.Response(state.status, content=state.raw, headers={"content-type": "application/json", **state.headers})
        return httpx.Response(state.status, json=envelope, headers={"content-type": "application/json", **state.headers})
    def client(**kwargs):
        assert kwargs == {"follow_redirects": False, "trust_env": False, "timeout": 25.0}
        return original_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return state


async def run(operation, arguments=None, **kwargs):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=arguments or {}, user_id=USER, credential_data=kwargs.pop("credential_data", CREDS), **kwargs)


def test_actual_factory_catalog_and_native_token_family():
    from coder.workflow.operation_catalog import get_operations_for_node_type, node_accepted_credential_types
    assert NODE_REGISTRY[NODE] is native.SkuVaultNode
    assert {op.name for op in get_operations_for_node_type(NODE)} == OPS
    assert node_accepted_credential_types(NODE) == {FAMILY}
    credential = native.SkuVaultAPITokensCredential.model_validate(CREDS)
    assert CREDS["tenant_token"] not in repr(credential) and CREDS["user_token"] not in repr(credential)


@pytest.mark.parametrize("family", [None, "", "foreign", "skuvault", "api_key"])
def test_null_or_foreign_family_rejected_before_normalization(family):
    with pytest.raises(ValueError):
        NodeFactory.create_node("fixture", NODE, {"config": {"operation": "list_external_warehouses"}, "credentials": {**CREDS, "credential_type": family}})


@pytest.mark.parametrize("field,value", [("tenant_token", "your-api-key"), ("user_token", "https://key.example"), ("tenant_token", " abc"), ("user_token", "a b"), ("user_token", "a\nb"), ("tenant_token", "a\x7fb"), ("user_token", "é")])
def test_credentials_hide_rejected_input(field, value):
    with pytest.raises(ValueError) as failure:
        native.SkuVaultAPITokensCredential.model_validate({**CREDS, field: value})
    assert "input_value=" not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(OPS))
async def test_all_declared_operations_use_exact_post_route_and_native_projection(provider, operation):
    data = (await run(operation, ARGS.get(operation)))["data"]
    assert provider.requests[-1].url.path == "/api/" + native.ROUTES[operation][0]
    assert not any(value in json.dumps(data) for value in ("private-custom", "private-download"))
    if operation in ("create_product", "update_product"):
        assert data == {"sku": "sku-42", "accepted": True, "http_status": 200, "readback_verified": False}
    if operation == "list_products":
        assert data["items"][0]["IsAlternateSKU"] is False and data["items"][0]["QuantityOnHand"] == 0
        assert not {"Cost", "SalePrice", "Attributes", "PictureUrl"} & data["items"][0].keys()
    if operation == "list_kits":
        assert not {"AvailableQuantity", "Cost"} & data["items"][0].keys()
    if operation == "list_inventory_by_location":
        assert data["items"][0]["Quantity"] == -1 and data["items"][0]["Reserve"] is False
    if "warehouse_id" in ARGS.get(operation, {}):
        assert data["requested_warehouse_id"] == ARGS[operation]["warehouse_id"]


@pytest.mark.asyncio
async def test_endpoint_specific_wire_fields_and_required_date_window(provider):
    await run("list_kits", {**WINDOW, "skus": ["kit-42"]})
    body = json.loads(provider.requests[-1].content)
    assert body["GetAvailableQuantity"] is False and body["IncludeKitCost"] is False and body["KitSKUs"] == ["kit-42"]
    assert "PageSize" not in body
    await run("list_warehouse_item_quantities", {"warehouse_id": 42, "page_size": 1000})
    assert json.loads(provider.requests[-1].content)["PageSize"] == "1000"
    await run("list_external_warehouse_quantities", {"warehouse_id": 43})
    assert json.loads(provider.requests[-1].content)["GetTotalFbaQuantities"] is False
    await run("list_kit_quantities", {"modified_after_utc": WINDOW["modified_after_utc"]})
    assert "ModifiedBeforeDateTimeUtc" not in json.loads(provider.requests[-1].content)
    for operation in ("list_external_warehouses", "list_locations"):
        await run(operation)
        assert set(json.loads(provider.requests[-1].content)) == {"TenantToken", "UserToken"}


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 1000])
async def test_known_page_size_avoids_fabricated_totals(provider, count):
    provider.records["products/getBrands"] = {"Brands": [{"Name": "Brand " + str(i), "IsEnabled": False} for i in range(count)]}
    data = (await run("list_brands", {"page_number": 2}))["data"]
    assert data["page_record_count"] == count and data["page_number"] == 2 and "total" not in data
    assert data["has_more"] is (None if count == 1000 else False)
    assert data["next_page_number"] == (3 if count == 1000 else None)


@pytest.mark.asyncio
async def test_unknown_page_size_and_alternate_rows_do_not_invent_completion(provider):
    for operation in ("list_warehouses", "list_kits"):
        data = (await run(operation, ARGS.get(operation)))["data"]
        assert data["has_more"] is None and data["next_page_number"] == 1
    provider.records["products/getProducts"]["Products"].append({**PRODUCT, "Sku": "alias-42", "IsAlternateSKU": True})
    data = (await run("list_products"))["data"]
    assert len(data["items"]) == 2 and data["items"][0]["Id"] == data["items"][1]["Id"]


@pytest.mark.asyncio
async def test_product_membership_and_explicit_blank_changes(provider):
    await run("update_product", {"sku": "sku-42", "clear_description": True, "metadata": {"part_number": "part-42"}})
    assert [r.url.path for r in provider.requests] == ["/api/products/getProduct", "/api/products/updateProduct"]
    assert json.loads(provider.requests[-1].content) == {"TenantToken": CREDS["tenant_token"], "UserToken": CREDS["user_token"], "Sku": "sku-42", "Description": "", "PartNumber": "part-42"}
    provider.requests.clear()
    provider.records["products/getProduct"]["Product"]["Sku"] = "foreign-42"
    with pytest.raises(ValueError, match="different"):
        await run("update_product", ARGS["update_product"])
    assert len(provider.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args", [("list_products", {"page_size": 999}), ("list_available_quantities", {"page_size": 5001}), ("list_kits", {}), ("list_kits", {**WINDOW, "modified_before_utc": "2020-01-01T00:00:00Z"}), ("list_item_quantities", {"modified_after_utc": "2026-99-01T00:00:00Z"}), ("get_warehouse_item_quantity", {"warehouse_id": True, "sku": "sku-42"}), ("get_product", {"sku": " bad"}), ("create_product", {"sku": "sku-42", "brand": "Missing parents"}), ("update_product", {"sku": "sku-42", "clear_description": "true"}), ("update_product", {"sku": "sku-42", "metadata": {"quantity": 9}}), ("update_product", {"sku": "sku-42", "metadata": {"description": "changed"}, "clear_description": True}), ("adjust_quantity", {})])
async def test_schema_rejects_invalid_or_undeclared_work_before_http(provider, op, args):
    with pytest.raises(ValueError):
        await run(op, args)
    assert provider.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 301, 400, 401, 403, 404, 409, 413, 500])
async def test_http_failure_is_private_and_not_retried(provider, status):
    provider.status, provider.override = status, {"Error": CREDS["user_token"]}
    with pytest.raises(ValueError) as failure:
        await run("list_external_warehouses")
    assert CREDS["user_token"] not in str(failure.value) and len(provider.requests) == 1


@pytest.mark.asyncio
async def test_throttle_reset_is_milliseconds_with_no_retry(provider):
    provider.status = 429
    provider.headers = {"X-RateLimit-Reset": "12345", "X-RateLimit-Limit": "5", "X-RateLimit-Remaining": "0"}
    with pytest.raises(native.SkuVaultRateLimited) as failure:
        await run("list_products")
    assert failure.value.metadata == {"retry_after_ms": 12345, "limit_per_minute": 5, "remaining": 0}
    assert "12345 milliseconds" in str(failure.value) and len(provider.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [{"Errors": ["private-provider-error"]}, {"Errors": "wrong-shape"}, {"Status": "ERROR"}, {"Success": False}, {"Error": "private-provider-error"}])
async def test_http_200_provider_failures_are_inconclusive_not_verified(provider, failure):
    provider.override = {**RESPONSES["inventory/getExternalWarehouses"], **failure}
    evidence = await collect_evidence(node_type=NODE, credential_data=CREDS, user_id=USER)
    assert evidence.reachable is None and evidence.samples == []
    assert "private-provider-error" not in json.dumps(evidence.__dict__)


@pytest.mark.asyncio
async def test_media_json_bounds_and_transport_privacy(provider, caplog):
    for headers, raw, override in [({"content-type": "text/html"}, None, None), ({}, b'{"Errors":[],"Errors":[],"Warehouses":[]}', None), ({}, b'{"Warehouses":[NaN]}', None), ({}, b"x" * (native.MAX_BYTES + 1), None), ({}, None, {"Errors": [], "Warehouses": [{"Id": 43}]}), ({}, None, {"Errors": [], "Warehouses": [] , "Status": False})]:
        provider.headers, provider.raw, provider.override = headers, raw, override
        with pytest.raises(ValueError):
            await run("list_external_warehouses")
    provider.headers, provider.raw, provider.override, provider.timeout = {}, None, None, True
    with caplog.at_level(logging.DEBUG), pytest.raises(ValueError) as failure:
        await run("list_external_warehouses")
    assert CREDS["user_token"] not in caplog.text + str(failure.value)
    assert failure.value.__suppress_context__ is True


@pytest.mark.asyncio
async def test_public_policy_filters_and_secret_reflection(provider):
    provider.dns_refused = True
    with pytest.raises(ValueError):
        await run("list_external_warehouses")
    assert provider.requests == []
    provider.dns_refused = False
    for secret in (CREDS["tenant_token"], CREDS["user_token"]):
        provider.override = {"Errors": [], "Warehouses": [{"Id": "43", "Name": secret}]}
        with pytest.raises(ValueError, match="credential material"):
            await run("list_external_warehouses")
    provider.override = None
    with pytest.raises(ValueError, match="outside"):
        await run("list_products", {"skus": ["other-sku"]})
    with pytest.raises(ValueError, match="outside"):
        await run("list_item_quantities", {"codes": ["other-code"]})


@pytest.mark.asyncio
async def test_actual_connect_and_collector_accept_only_completed_protected_reads(provider):
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True and native.SkuVaultNode.connection_evidence.proves == "account"
    assert verdict.evidence.samples[0].label == "Fixture external"
    provider.records["inventory/getExternalWarehouses"] = {"Warehouses": []}
    evidence = await collect_evidence(node_type=NODE, credential_data=CREDS, user_id=USER)
    assert evidence.reachable is True and evidence.samples == [] and evidence.account_label is None
    for status in (401, 403, 404):
        provider.status = status
        verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER)
        assert not verdict.ok and verdict.evidence.reachable is False


@pytest.mark.asyncio
async def test_staging_credential_hooks_validate_non_rotating_tokens(provider):
    assert await native.SkuVaultNode.freshen_credential(CREDS) == CREDS
    assert await native.SkuVaultNode.validate_credential_access(CREDS) == {"valid": True}
    provider.status = 401
    with pytest.raises(ValueError, match="authentication failed"):
        await native.SkuVaultNode.validate_credential_access(CREDS)


@pytest.mark.asyncio
async def test_staging_runner_resolves_stored_connection(provider, monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))
    resolver = AsyncMock(return_value=CREDS)
    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", resolver)
    result = await run("list_external_warehouses", credential_id=CID, credential_data=None)
    assert result["data"]["items"][0]["Name"] == "Fixture external"
    resolver.assert_awaited_once_with(CID, USER, None, None, None)
