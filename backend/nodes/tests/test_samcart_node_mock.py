"""SamCart factory tests with provider-shaped fixtures; no real account or key."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import samcart_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-samcart-key"
FIXTURES = Path(__file__).parent / "fixtures" / "samcart"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="samcart-test", node_type="automation-samcart", node_data={
        "config": config, "credentials": {"credential_type": "samcart_api_key", "api_key": KEY},
    })


def transport(monkeypatch, payload, status=200, headers=None):
    requests = []

    def respond(request):
        requests.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload, headers=headers)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# These expected paths are written independently of the node's dispatch table.
READS = [
    ("list_customers", {}, "/customers", True),
    ("get_customer", {"customer_id": 1337}, "/customers/1337", False),
    ("list_products", {}, "/products", True),
    ("get_product", {"product_id": 1337}, "/products/1337", False),
    ("list_orders", {}, "/orders", True),
    ("get_order", {"order_id": 1337}, "/orders/1337", False),
    ("list_charges", {}, "/charges", True),
    ("get_charge", {"charge_id": 1337}, "/charges/1337", False),
    ("list_subscriptions", {}, "/subscriptions", True),
    ("get_subscription", {"subscription_id": 1337}, "/subscriptions/1337", False),
    ("list_failed_charges", {}, "/failed-charges", True),
    ("get_failed_charge", {"failed_charge_id": 1337}, "/failed-charges/1337", False),
    ("list_refunds", {}, "/refunds", True),
    ("list_charge_refunds", {"charge_id": 1337}, "/charges/1337/refunds", True),
    ("list_customer_orders", {"customer_id": 1337}, "/customers/1337/orders", True),
    ("list_customer_subscriptions", {"customer_id": 1337}, "/customers/1337/subscriptions", True),
    ("list_customer_charges", {"customer_id": 1337}, "/customers/1337/charges", True),
    ("list_order_charges", {"order_id": 1337}, "/orders/1337/charges", True),
    ("get_order_customer", {"order_id": 1337}, "/orders/1337/customer", False),
    ("list_order_subscriptions", {"order_id": 1337}, "/orders/1337/subscriptions", True),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,path,is_list", READS)
async def test_samcart_read_routes(monkeypatch, operation, fields, path, is_list):
    record = {"id": 1337, "name": "Book"}
    payload = {"data": [record], "pagination": {"next": None, "prev": None}} if is_list else record
    requests = transport(monkeypatch, payload)
    result = await node({"operation": operation, **fields}).execute({})
    assert result["status"] == "success"
    assert result["data"] == payload
    assert result["items" if is_list else "item"] == ([record] if is_list else record)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.path == "/v1" + path
    assert request.url.host == "api.samcart.com" and request.url.scheme == "https"
    assert request.headers["sc-api"] == KEY and request.headers["Accept"] == "application/json"
    assert KEY not in str(result)


WRITES = [
    ("update_order_custom_field", {"order_id": 1337, "custom_field_slug": "custom_zL6FLFM3", "custom_field_data": "America"}, "PUT", "/orders/1337", {"custom_field_slug": "custom_zL6FLFM3", "custom_field_data": "America"}),
    ("refund_charge", {"charge_id": 1337, "amount": 2500}, "POST", "/refunds/charges/1337/", {"amount": 2500}),
    ("cancel_subscription", {"subscription_id": 1337, "silent_cancel": True}, "POST", "/subscriptions/1337/cancel", {"silent_cancel": True}),
    ("schedule_cancel_subscription", {"subscription_id": 1337, "cancel_when": "custom", "schedule_date": "2022-04-08"}, "POST", "/subscriptions/1337/scheduleCancel", {"cancel_when": "custom", "schedule_date": "2022-04-08"}),
    ("update_subscription", {"subscription_id": 1337, "next_rebilling_date": "2027-06-15T00:00:00Z"}, "POST", "/subscriptions/1337/update", {"next_rebilling_date": "2027-06-15T00:00:00Z"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path,body", WRITES)
async def test_samcart_write_contract(monkeypatch, operation, fields, method, path, body):
    requests = transport(monkeypatch, {"id": 1337})
    result = await node({"operation": operation, **fields}).execute({})
    assert result["status"] == "success" and result["item"]["id"] == 1337
    assert len(requests) == 1
    assert requests[0].method == method and requests[0].url.path == "/v1" + path
    assert json.loads(requests[0].content) == body
    assert not requests[0].url.query


@pytest.mark.asyncio
async def test_samcart_documented_customer_and_cursor(monkeypatch):
    fixture = json.loads((FIXTURES / "customers.json").read_text())
    requests = transport(monkeypatch, fixture)
    config = {"operation": "list_customers", "email": "jdoe@gmail.com", "limit": 50,
              "offset": 100, "dir": "prev", "created_at_min": "2025-01-16T14:30:00Z"}
    result = await node(config).execute({})
    assert result["items"][0]["email"] == "jdoe@gmail.com"
    assert result["pagination"] == fixture["pagination"]
    assert dict(requests[0].url.params) == {"email": "jdoe@gmail.com", "limit": "50", "offset": "100", "dir": "prev", "created_at_min": "2025-01-16T14:30:00Z"}
    assert len(requests) == 1  # Pagination URLs are data, never followed with our key.


@pytest.mark.asyncio
async def test_samcart_false_filter_empty_page_and_full_refund(monkeypatch):
    requests = transport(monkeypatch, {"data": [], "pagination": {"next": None, "prev": None}})
    result = await node({"operation": "list_orders", "test_mode": False}).execute({})
    assert result["items"] == [] and requests[0].url.params["test_mode"] == "false"
    requests = transport(monkeypatch, {"id": 1337})
    await node({"operation": "refund_charge", "charge_id": 1337}).execute({})
    assert json.loads(requests[0].content) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 409, 422, 429, 504])
async def test_samcart_errors_do_not_retry_or_leak_keys(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + KEY}, status, {"Retry-After": "31"})
    result = await node({"operation": "cancel_subscription", "subscription_id": 1337}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["retry_after"] == "31" and KEY not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_samcart_timeout_and_malformed_response_are_errors(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("ambiguous write"))
    result = await node({"operation": "refund_charge", "charge_id": 1337}).execute({})
    assert result["write_outcome_unknown"] is True and len(requests) == 1
    for payload in [None, "HTML", {"success": False, "error": "failed"}, {}]:
        transport(monkeypatch, payload)
        assert (await node({"operation": "list_products"}).execute({}))["status"] == "error"


@pytest.mark.parametrize("config", [
    {"operation": "get_order", "order_id": "../../orders"},
    {"operation": "get_order", "order_id": 0},
    {"operation": "refund_charge", "charge_id": 1337, "amount": -1},
    {"operation": "list_products", "limit": 101},
    {"operation": "list_orders", "created_at_min": "yesterday"},
    {"operation": "list_orders", "created_at_min": "2025-01-16T14:30:00"},
    {"operation": "schedule_cancel_subscription", "subscription_id": 1337, "cancel_when": "custom"},
])
def test_samcart_invalid_config(config):
    with pytest.raises(ValidationError):
        node(config)


def test_samcart_manual_credential_has_default_type_and_no_hidden_requirements():
    credential = native.SamCartApiKeyCredential(api_key=KEY)
    assert credential.credential_type == "samcart_api_key"
    assert native.SamCartNode.connection_evidence.operation == "list_products"


@pytest.mark.asyncio
async def test_samcart_failed_charge_error_is_resource_data(monkeypatch):
    payload = {"id": 1337, "error": "Card declined"}
    transport(monkeypatch, payload)
    result = await node({"operation": "get_failed_charge", "failed_charge_id": 1337}).execute({})
    assert result["status"] == "success" and result["item"] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("success,expected", [("true", "success"), ("false", "error")])
async def test_samcart_custom_field_string_success_flag(monkeypatch, success, expected):
    # updateCustomFieldsByOrderId declares success as a string, not a boolean.
    payload = {"success": success, "data": "custom_zL6FLFM3 updated to: 'America'"}
    transport(monkeypatch, payload)
    result = await node({"operation": "update_order_custom_field", "order_id": 1337,
                         "custom_field_slug": "custom_zL6FLFM3", "custom_field_data": "America"}).execute({})
    assert result["status"] == expected
