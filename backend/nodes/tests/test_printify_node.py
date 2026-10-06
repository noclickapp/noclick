"""Native transport/parent/privacy regressions; synthetic HTTP only, no accounts.

These source fixtures are unrun until a root runtime lane is granted.
"""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import printify_node as node
from utils import ssrf

TOKEN = "fixture-printify-bearer-7de693"
CREDENTIAL = {"credential_type": "printify_pat", "personal_access_token": TOKEN, "brand": "printify"}
PRODUCT = {"id": "product-fixture", "shop_id": 42, "title": "Mug", "description": "Ceramic mug", "is_locked": False, "tags": ["Home"], "variants": [{"price": 900, "cost": 500}], "user_id": 13, "safety_information": "contact-private@example.test", "print_areas": [{"secret": "artwork"}], "images": [{"src": "https://private.example.test/asset?token=secret"}]}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    async def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.headers["User-Agent"] == "NoClick Printify integration"
        assert TOKEN not in str(request.url)
        response = replies[(request.method, request.url.path)]
        return response(request) if callable(response) else httpx.Response(200, json=response)
    actual_client = ssrf.guarded_async_client
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual_client(transport=httpx.MockTransport(handler), **kwargs))
    return calls, replies


@pytest.mark.parametrize("brand,host,prefix", [("printify", "api.printify.com", "/v1"), ("printful_enterprise", "enterprise.printful.com", "/api/pfy/public/v1")])
async def test_documented_fixed_brand_hosts_and_closed_shop_output(transport, brand, host, prefix):
    calls, replies = transport
    replies[("GET", prefix + "/shops.json")] = [{"id": 42, "title": "Fixture shop", "sales_channel": "disconnected", "token": TOKEN, "account_email": "private@example.test"}]
    result = await node.request_operation({**CREDENTIAL, "brand": brand}, node.ListShops())
    assert result == {"data": {"items": [{"id": "42", "title": "Fixture shop", "sales_channel": "disconnected"}]}}
    assert calls[0].url.host == host and calls[0].url.scheme == "https"


async def test_explicit_product_page_and_no_returned_url_following(transport):
    calls, replies = transport
    replies[("GET", "/v1/shops.json")] = [{"id": 42, "title": "Shop", "sales_channel": "disconnected"}]
    replies[("GET", "/v1/shops/42/products.json")] = {"current_page": 2, "last_page": 3, "data": [PRODUCT], "next_page_url": "https://attacker.example.test/?token=secret"}
    result = (await node.request_operation(CREDENTIAL, node.ListProducts(shop_id="42", page=2, limit=10)))["data"]
    assert result["next_page"] == 3 and result["page"] == 2
    assert dict(calls[-1].url.params) == {"page": "2", "limit": "10"}
    assert len(calls) == 2 and all(call.url.host == "api.printify.com" for call in calls)
    assert not {"user_id", "variants", "images", "safety_information", "print_areas"}.intersection(result["items"][0])


async def test_foreign_shop_refuses_before_product_read(transport):
    calls, replies = transport
    replies[("GET", "/v1/shops.json")] = []
    with pytest.raises(ValueError, match="Selected shop"):
        await node.request_operation(CREDENTIAL, node.GetProduct(shop_id="42", product_id="product-fixture"))
    assert [call.url.path for call in calls] == ["/v1/shops.json"]


@pytest.mark.parametrize("change", [{"shop_id": 99}, {"id": "different"}, {"is_locked": True}, {"is_locked": None}])
async def test_parent_identity_or_lock_denies_all_mutation(transport, change):
    calls, replies = transport
    replies[("GET", "/v1/shops.json")] = [{"id": 42, "title": "Shop", "sales_channel": "disconnected"}]
    replies[("GET", "/v1/shops/42/products/product-fixture.json")] = {**PRODUCT, **change}
    with pytest.raises(ValueError):
        await node.request_operation(CREDENTIAL, node.UpdateProductMetadata(shop_id="42", product_id="product-fixture", title="New title"))
    assert len(calls) == 2 and all(call.method == "GET" for call in calls)


async def test_partial_metadata_put_preserves_other_product_fields(transport):
    calls, replies = transport
    replies[("GET", "/v1/shops.json")] = [{"id": 42, "title": "Shop", "sales_channel": "disconnected"}]
    route = "/v1/shops/42/products/product-fixture.json"
    replies[("GET", route)] = PRODUCT
    replies[("PUT", route)] = {**PRODUCT, "title": "New title", "description": ""}
    result = await node.request_operation(CREDENTIAL, node.UpdateProductMetadata(shop_id="42", product_id="product-fixture", title="New title", clear_description=True))
    assert json.loads(calls[-1].content) == {"title": "New title", "description": ""}
    assert result["data"]["description"] == "" and result["data"]["title"] == "New title"
    assert [call.method for call in calls] == ["GET", "GET", "PUT"]
    assert not any("publish" in call.url.path or "orders" in call.url.path for call in calls)


async def test_variant_parent_scope_is_verified(transport):
    calls, replies = transport
    replies[("GET", "/v1/catalog/blueprints/5/print_providers.json")] = [{"id": 7, "title": "Provider"}]
    with pytest.raises(ValueError, match="does not belong"):
        await node.request_operation(CREDENTIAL, node.ListVariants(blueprint_id="5", blueprint_print_provider_id="8"))
    assert len(calls) == 1


async def test_actual_variant_envelope_and_stock_query(transport):
    calls, replies = transport
    replies[("GET", "/v1/catalog/blueprints/5/print_providers.json")] = [{"id": 7, "title": "Provider"}]
    replies[("GET", "/v1/catalog/blueprints/5/print_providers/7/variants.json")] = {"id": 7, "title": "Provider", "variants": [{"id": 123, "title": "Small", "options": {"size": "S"}, "decoration_methods": ["dtg"], "cost": 500}]}
    result = await node.request_operation(CREDENTIAL, node.ListVariants(blueprint_id="5", blueprint_print_provider_id="7", show_out_of_stock=True))
    assert dict(calls[-1].url.params) == {"show-out-of-stock": "1"}
    assert result["data"]["items"] == [{"id": "123", "title": "Small", "options": {"size": "S"}, "decoration_methods": ["dtg"]}]


@pytest.mark.parametrize("status", [202, 204, 301, 401, 403, 429, 500])
async def test_non_200_is_safe_and_never_retried(transport, status):
    calls, replies = transport
    replies[("GET", "/v1/shops.json")] = lambda _: httpx.Response(status, headers={"Retry-After": "7", "Location": "https://attacker.example.test"}, text=TOKEN)
    with pytest.raises(node.PrintifyAPIError) as error:
        await node.request_operation(CREDENTIAL, node.ListShops())
    assert TOKEN not in str(error.value) and error.value.retry_after == 7
    assert len(calls) == 1


@pytest.mark.parametrize("content", [b'{"id":1,"id":2}', b'{"value":NaN}', b'{"value":1e999}', b'<html>token</html>', b'null'])
async def test_malformed_nonfinite_or_wrong_format_has_no_partial_output(transport, content):
    calls, replies = transport
    replies[("GET", "/v1/shops.json")] = lambda _: httpx.Response(200, content=content, headers={"Content-Type": "application/json"})
    with pytest.raises(ValueError):
        await node.request_operation(CREDENTIAL, node.ListShops())
    assert len(calls) == 1


async def test_decoded_size_bound_is_loud(transport):
    _, replies = transport
    replies[("GET", "/v1/shops.json")] = lambda _: httpx.Response(200, content=b" " * (node.MAX_BYTES + 1), headers={"Content-Type": "application/json"})
    with pytest.raises(ValueError, match="2 MiB"):
        await node.request_operation(CREDENTIAL, node.ListShops())


async def test_picker_continuation_binds_token_brand_parent_and_search(transport):
    calls, replies = transport
    replies[("GET", "/v1/shops.json")] = [{"id": 42, "title": "Shop", "sales_channel": "disconnected"}]
    replies[("GET", "/v1/shops/42/products.json")] = {"current_page": 1, "last_page": 2, "data": [PRODUCT]}
    first = await node.PrintifyNode.load_field_options("product_id", CREDENTIAL, {"shop_id": "42"}, search="Mug")
    for credential, context, search in [(CREDENTIAL, {"shop_id": "99"}, "Mug"), ({**CREDENTIAL, "brand": "printful_enterprise"}, {"shop_id": "42"}, "Mug"), ({**CREDENTIAL, "personal_access_token": "another-fixture-token"}, {"shop_id": "42"}, "Mug"), (CREDENTIAL, {"shop_id": "42"}, "Other")]:
        with pytest.raises(ValueError, match="Picker page"):
            await node.PrintifyNode.load_field_options("product_id", credential, context, page_token=first["next_page_token"], search=search)
    assert len(calls) == 2


@pytest.mark.parametrize("raw", [{}, {"credential_type": "slack_oauth", "access_token": TOKEN}, {"credential_type": "printify_pat", "personal_access_token": "https://secret.example.test"}])
def test_raw_family_is_strict_for_parse_and_validation(raw):
    config = {"credentials": raw, "config": {"operation": "list_shops"}}
    with pytest.raises(ValueError):
        node.PrintifyNode.parse_config(config)
    assert node.PrintifyNode.validate_config(config)["valid"] is False


async def test_expired_supplied_oauth_has_zero_provider_calls(transport):
    calls, _ = transport
    with pytest.raises(ValueError, match="expired"):
        await node.request_operation({"credential_type": "printify_oauth_access_token", "access_token": TOKEN, "expires_at": "2020-01-01T00:00:00+00:00"}, node.ListShops())
    assert calls == []
