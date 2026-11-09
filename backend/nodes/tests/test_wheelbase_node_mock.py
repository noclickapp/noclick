"""Run the discovered node through the real factory with provider HTTP mocked."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import wheelbase_node as wb
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from utils import ssrf

TOKEN = "fixture-wheelbase-token"
AUTH = {"credential_type": "wheelbase_api_token", "api_token": TOKEN}
USER = "00000000-0000-4000-8000-000000000001"
ACCOUNT = json.loads((Path(__file__).parent / "fixtures/wheelbase/account.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.wheelbasepro.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        status, payload = replies.pop(0)
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(wb, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-wheelbase", operation=operation,
        arguments=arguments or {}, credential_data=AUTH, user_id=USER)


# Expected routes are independent of the dispatch table in the implementation.
CASES = [
    ("get_account", {}, "GET", "/v1/me", 200),
    ("list_listings", {}, "GET", "/v1/listings", 200),
    ("get_listing", {"listing_id": 452064}, "GET", "/v1/listings/452064", 200),
    ("update_listing", {"listing_id": 452064, "price_per_day": 23400}, "PATCH", "/v1/listings/452064", 200),
    ("list_listing_addons", {"listing_id": 452064}, "GET", "/v1/listings/452064/addons", 200),
    ("get_listing_availability", {"listing_id": 452064}, "GET", "/v1/listings/452064/availability", 200),
    ("list_insurance_options", {"listing_id": 452064}, "GET", "/v1/listings/452064/insurance-options", 200),
    ("create_quote", {"listing_id": 452064, "start_date": "2026-10-15", "end_date": "2026-10-18"}, "POST", "/v1/quotes", 200),
    ("list_bookings", {}, "GET", "/v1/bookings", 200),
    ("create_booking", {"listing_id": 8339, "start_date": "2026-10-15", "end_date": "2026-10-18"}, "POST", "/v1/bookings", 201),
    ("get_booking", {"booking_id": 42}, "GET", "/v1/bookings/42", 200),
    ("update_booking", {"booking_id": 42, "guests": 2}, "PATCH", "/v1/bookings/42", 200),
    ("approve_booking", {"booking_id": 42}, "POST", "/v1/bookings/42/approve", 200),
    ("decline_booking", {"booking_id": 42}, "POST", "/v1/bookings/42/decline", 200),
    ("cancel_booking", {"booking_id": 42}, "POST", "/v1/bookings/42/cancel", 200),
    ("create_booking_link", {"booking_id": 42, "type": "payment"}, "POST", "/v1/bookings/42/links", 201),
    ("list_booking_documents", {"booking_id": 42}, "GET", "/v1/bookings/42/documents", 200),
    ("list_booking_payments", {"booking_id": 42}, "GET", "/v1/bookings/42/payments", 200),
    ("get_booking_messages", {"booking_id": 42}, "GET", "/v1/bookings/42/messages", 200),
    ("list_customers", {}, "GET", "/v1/customers", 200),
    ("create_customer", {"first_name": "Fixture", "last_name": "Renter", "email": "renter@example.com"}, "POST", "/v1/customers", 201),
    ("get_customer", {"customer_id": 42}, "GET", "/v1/customers/42", 200),
    ("update_customer", {"customer_id": 42, "phone": "5550100"}, "PATCH", "/v1/customers/42", 200),
    ("list_locations", {}, "GET", "/v1/locations", 200),
    ("list_message_threads", {}, "GET", "/v1/messages/threads", 200),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,status", CASES)
async def test_each_operation_is_one_contract_request(transport, operation, config, method, path, status):
    requests, queue = transport
    payload = ACCOUNT if operation == "get_account" else {"id": 42, "name": "Fixture"}
    queue.append((status, payload))
    result = await run(operation, config)
    assert result["status"] == "success" and result["data"] == payload
    assert result["http_status"] == status
    assert len(requests) == 1 and queue == []
    assert (requests[0].method, requests[0].url.path) == (method, path)
    if method in {"POST", "PATCH"}:
        body = json.loads(requests[0].content)
        assert "operation" not in body and "booking_id" not in body
        for key, value in config.items():
            if key not in {"listing_id", "booking_id", "customer_id"} or operation in {"create_quote", "create_booking"}:
                assert body[key] == value


@pytest.mark.asyncio
async def test_page_filters_and_metadata_are_preserved(transport):
    requests, queue = transport
    payload = {"data": [{"id": 42}], "page": 2, "page_size": 20, "total": None}
    queue.append((200, payload))
    result = await run("list_customers", {"search": "smith", "page": 2, "page_size": 20, "repeat_guest": False})
    assert dict(requests[0].url.params) == {"search": "smith", "page": "2", "page_size": "20", "repeat_guest": "false"}
    assert result["data"] == payload["data"] and result["page"] == 2 and result["total"] is None


@pytest.mark.asyncio
async def test_dates_addons_idempotency_and_email_controls(transport):
    requests, queue = transport
    queue.extend([(201, {"id": 42}), (200, {"id": 42}), (200, {"id": 42})])
    await run("create_booking", {"listing_id": 8339, "start_date": "2026-10-15", "end_date": "2026-10-18",
        "idempotency_key": "booking-2026-10-15-user42", "addons": [{"id": 4821, "quantity": 2}]})
    assert requests[0].headers["idempotency-key"] == "booking-2026-10-15-user42"
    assert "idempotency_key" not in json.loads(requests[0].content)
    assert json.loads(requests[0].content)["addons"] == [{"id": 4821, "quantity": 2}]
    await run("approve_booking", {"booking_id": 42, "notify": False, "reason": "Your quote"})
    assert json.loads(requests[1].content) == {"notify": False, "reason": "Your quote"}
    await run("update_booking", {"booking_id": 42, "addons": []})
    assert json.loads(requests[2].content) == {"addons": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 409, 422, 429, 500, 302])
async def test_errors_are_verbatim_redacted_and_never_retried(transport, status):
    requests, queue = transport
    queue.append((status, {"error": {"code": "rejected", "message": "Provider refused " + TOKEN}}))
    result = await run("approve_booking", {"booking_id": 42})
    assert result["success"] is False and result["http_status"] == status
    assert result["message"] == "Provider refused [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_connection_names_the_account_without_write_scopes(transport):
    requests, queue = transport
    queue.append((200, {**ACCOUNT, "scopes": []}))
    result = await collect_evidence(node_type="automation-wheelbase", credential_data=AUTH, user_id=USER)
    assert result.reachable is True and result.account_label == "Fixture Rental Fleet"
    assert len(requests) == 1 and requests[0].url.path == "/v1/me"


@pytest.mark.asyncio
async def test_timeout_is_not_retried(transport):
    requests, queue = transport
    queue.append((0, httpx.ReadTimeout("fixture timeout")))
    with pytest.raises(ValueError, match="check the provider"):
        await run("create_booking", {"listing_id": 8339, "start_date": "2026-10-15", "end_date": "2026-10-18"})
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_booking", "booking_id": "../me"},
    {"operation": "update_listing", "listing_id": 1},
    {"operation": "update_customer", "customer_id": 1, "email": "bad"},
    {"operation": "create_quote", "listing_id": 1, "start_date": "2026-10-18", "end_date": "2026-10-15"},
    {"operation": "create_booking_link", "booking_id": 1, "type": "arbitrary"},
    {"operation": "list_customers", "page_size": 201},
    {"operation": "update_booking", "booking_id": 1, "addons": [{"id": 1, "quantity": 101}]},
])
def test_bad_input_is_rejected_before_http(config):
    with pytest.raises((ValidationError, ValueError)):
        wb.WheelbaseNode.parse_config({"config": config, "credentials": AUTH})


def test_manual_credential_has_default_type_and_one_required_field():
    model = wb.WheelbaseAPITokenCredential(api_token=TOKEN)
    assert model.credential_type == "wheelbase_api_token"
    assert {k for k, f in type(model).model_fields.items() if f.is_required()} == {"api_token"}
    with pytest.raises(ValidationError):
        wb.WheelbaseAPITokenCredential(api_token="Bearer " + TOKEN)


@pytest.mark.asyncio
async def test_availability_query_names_and_json_failure(transport):
    requests, queue = transport
    queue.extend([(200, {"listing_id": 452064, "window": {"from": "2026-07-06", "to": "2027-07-06"}, "unavailable": []}), (200, b"<html>not the API</html>")])
    await run("get_listing_availability", {"listing_id": 452064, "from_date": "2026-07-06", "to_date": "2027-07-06"})
    assert dict(requests[0].url.params) == {"from": "2026-07-06", "to": "2027-07-06"}
    with pytest.raises(ValueError, match="non-JSON"):
        await run("get_account")
