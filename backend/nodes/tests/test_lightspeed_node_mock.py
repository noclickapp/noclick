"""Exercise the native execution seam with provider examples and offline HTTP."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import lightspeed_node as ls
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {
    "credential_type": "lightspeed_api_token",
    "domain_prefix": "example",
    "api_token": "fixture-token-123456789",
}
USER = "00000000-0000-4000-8000-000000000001"
EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/lightspeed/responses.json").read_text()
)


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        assert request.url.host == "example.retail.lightspeed.app"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_token"]
        assert AUTH["api_token"] not in str(request.url)
        return replies.pop(0)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        ls,
        "guarded_async_client",
        lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(
        node_type="automation-lightspeed",
        operation=operation,
        arguments=arguments or {},
        credential_data=dict(auth),
        user_id=USER,
    )


CASES = [
    ("get_retailer", {}, "GET", "/retailer"),
    ("list_customers", {}, "GET", "/customers"),
    ("get_customer", {"customer_id": "customer-1"}, "GET", "/customers/customer-1"),
    (
        "create_customer",
        {
            "first_name": "Tony",
            "last_name": "Stark",
            "do_not_email": True,
            "enable_promotional_sms": False,
        },
        "POST",
        "/customers",
    ),
    (
        "update_customer",
        {
            "customer_id": "customer-1",
            "first_name": "Tony",
            "last_name": "Stark",
            "note": "Updated",
        },
        "PUT",
        "/customers/customer-1",
    ),
    ("list_products", {"sku": "SKU-1"}, "GET", "/products"),
    ("get_product", {"product_id": "product-1"}, "GET", "/products/product-1"),
    ("list_sales", {}, "GET", "/sales"),
    ("get_sale", {"sale_id": "sale-1"}, "GET", "/sales/sale-1"),
    (
        "list_product_inventory",
        {"product_id": "product-1", "variants": True},
        "GET",
        "/inventory/product-1",
    ),
    ("list_outlets", {}, "GET", "/outlets"),
    ("get_outlet", {"outlet_id": "outlet-1"}, "GET", "/outlets/outlet-1"),
    ("list_registers", {}, "GET", "/registers"),
    ("get_register", {"register_id": "register-1"}, "GET", "/registers/register-1"),
    ("list_brands", {}, "GET", "/brands"),
    ("get_brand", {"brand_id": "brand-1"}, "GET", "/brands/brand-1"),
    ("create_brand", {"name": "Peak"}, "POST", "/brands"),
    ("update_brand", {"brand_id": "brand-1", "name": "Peak"}, "PUT", "/brands/brand-1"),
    ("list_suppliers", {}, "GET", "/suppliers"),
    ("get_supplier", {"supplier_id": "supplier-1"}, "GET", "/suppliers/supplier-1"),
    (
        "create_supplier",
        {"name": "Best Supplies", "contact_email": "contact@example.test"},
        "POST",
        "/suppliers",
    ),
    ("list_customer_groups", {}, "GET", "/customer_groups"),
    ("list_taxes", {}, "GET", "/taxes"),
]


@pytest.mark.parametrize("operation,arguments,method,path", CASES)
async def test_all_operation_routes_and_bodies(
    transport, operation, arguments, method, path
):
    requests, replies = transport
    payload = (
        [{"id": "record-1", "current_inventory_level": 21}]
        if operation == "list_product_inventory"
        else {"data": {"id": "record-1"}}
    )
    replies.append(httpx.Response(200, json=payload))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == "/api/2026-10" + path
    if method != "GET":
        expected = {
            k: v
            for k, v in arguments.items()
            if not k.endswith("_id") and not k.startswith("contact_")
        }
        if operation == "create_supplier":
            expected["contact"] = {"email": "contact@example.test"}
        assert json.loads(request.content) == expected
    if operation == "list_products":
        assert request.url.params["sku"] == "SKU-1"
    if operation == "list_product_inventory":
        assert request.url.params["variants"] == "true"
        assert result["data"] == payload


@pytest.mark.parametrize(
    "operation,arguments,key",
    [
        ("list_customers", {}, "GET /customers"),
        ("get_customer", {"customer_id": "customer-1"}, "GET /customers/{id}"),
        (
            "update_customer",
            {"customer_id": "customer-1", "first_name": "Tony", "last_name": "Stark"},
            "PUT /customers/{id}",
        ),
        ("list_outlets", {}, "GET /outlets"),
        ("list_brands", {}, "GET /brands"),
        ("list_suppliers", {}, "GET /suppliers"),
        ("get_supplier", {"supplier_id": "supplier-1"}, "GET /suppliers/{supplier_id}"),
        ("list_taxes", {}, "GET /taxes"),
        ("list_customer_groups", {}, "GET /customer_groups"),
        (
            "list_product_inventory",
            {"product_id": "product-1"},
            "GET /inventory/{product_id}",
        ),
    ],
)
async def test_documented_responses_preserved(transport, operation, arguments, key):
    body = EXAMPLES[key]["body"]
    transport[1].append(httpx.Response(200, json=body))
    result = await run(operation, arguments)
    if isinstance(body, list):
        assert result["data"] == body
    else:
        for k, v in body.items():
            assert result[k] == v


async def test_version_cursor_and_false_values(transport):
    body = EXAMPLES["GET /brands"]["body"]
    transport[1].append(httpx.Response(200, json=body))
    result = await run(
        "list_brands", {"after": 100, "before": 200, "page_size": 25, "deleted": False}
    )
    assert dict(transport[0][0].url.params) == {
        "after": "100",
        "before": "200",
        "page_size": "25",
        "deleted": "false",
    }
    assert result["version"] == body["version"]


async def test_supplier_contact_is_sent_even_when_absent(transport):
    transport[1].append(httpx.Response(200, json={"data": "supplier-1"}))
    await run("create_supplier", {"name": "Supplier"})
    assert json.loads(transport[0][0].content) == {"name": "Supplier", "contact": None}


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_provider_errors_and_no_retry(transport, status):
    transport[1].append(
        httpx.Response(status, json={"error": "rejected " + AUTH["api_token"]})
    )
    result = await run("list_outlets")
    assert result["status"] == "error" and result["status_code"] == status
    assert "rejected" in result["error"] and AUTH["api_token"] not in str(result)
    assert len(transport[0]) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>login</html>"),
        httpx.Response(200, json={"errors": ["denied"]}),
    ],
)
async def test_invalid_success_does_not_verify(transport, response):
    transport[1].append(response)
    try:
        result = await run("list_outlets")
    except ValueError:
        return
    assert result["status"] == "error"


@pytest.mark.parametrize(
    "field,value",
    [
        ("domain_prefix", "https://evil.test"),
        ("domain_prefix", "store.retail.lightspeed.app"),
        ("domain_prefix", "a/../b"),
        ("api_token", "Bearer abc"),
        ("api_token", "abc\r\nx: y"),
        ("api_token", "https://example.test"),
    ],
)
def test_invalid_credentials(field, value):
    with pytest.raises(ValidationError):
        ls.LightspeedTokenCredential(**{**AUTH, field: value})


def test_credential_defaults_and_shaping():
    c = ls.LightspeedTokenCredential(
        domain_prefix=" Example ", api_token=" fixture-token-123456789 \n"
    )
    assert c.credential_type == "lightspeed_api_token"
    assert c.domain_prefix == "example" and c.api_token == AUTH["api_token"]


def test_reject_path_injection_and_unknown_fields():
    with pytest.raises(ValueError):
        ls.LightspeedNode.parse_config(
            {
                "config": {"operation": "get_customer", "customer_id": "../outlets"},
                "credentials": AUTH,
            }
        )
    with pytest.raises(ValueError):
        ls.LightspeedNode.parse_config(
            {
                "config": {"operation": "create_brand", "name": "Brand", "admin": True},
                "credentials": AUTH,
            }
        )
