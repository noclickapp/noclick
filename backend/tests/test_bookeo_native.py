"""Unrun native Bookeo seams. Synthetic transport/SQL, never provider I/O."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from nodes import bookeo_node as bk
from nodes.core import connection_evidence as ce, credential_connect as cc, run_op
from nodes.core.registry import NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, ssrf

TYPE, FAMILY = "automation-bookeo", "bookeo_api_key"
ID, USER = "00000000-0000-4000-8000-000000000042", "00000000-0000-4000-8000-000000000001"
CREDS = {"secret_key": "synthetic-bookeo-secret-canary", "api_key": "synthetic-bookeo-account-canary", "expected_account_id": "account42"}
WINDOW = {"start_time": "2026-10-06T09:00:00Z", "end_time": "2026-10-07T09:00:00Z"}
PRODUCT = {"productId": "product42", "name": "Fixture Product", "type": "fixed", "apiBookingsAllowed": True, "shownToCustomers": True, "prepaidOnly": False, "membersOnly": False}
CUSTOMER = {"id": "customer42", "creationTime": "2026-10-06T09:00:00Z", "firstName": "PrivateName", "lastName": "PrivateSurname", "emailAddress": "private@example.test", "credit": {"amount": 77}, "phoneNumbers": [{"number": "private-phone", "type": "home"}]}
BOOKING = {"bookingNumber": "000042", "productId": "product42", "eventId": "event42", "customerId": "customer42", "participants": {"numbers": [{"peopleCategoryId": "adult", "number": 1}]}, "accepted": False, "startTime": WINDOW["start_time"], "endTime": WINDOW["end_time"], "price": {"total": 77}, "customer": CUSTOMER}


@pytest.fixture
def ensure_native_db_pool():
    yield


def factory(op, arguments=None, credential=None, current=None):
    data = {"config": {"operation": op, **(arguments or {})}, "credentials": deepcopy(CREDS if credential is None else credential)}
    if current:
        data.update(credential_id=ID, _approval_pool=current.pool)
    return NodeFactory.create_node(node_id="bookeo-fixture", node_type=TYPE, node_data=data, user_id=USER)


@pytest_asyncio.fixture
async def wire(monkeypatch):
    state = SimpleNamespace(calls=[], override=None, response_hook=None, account="account42", permissions=["customers_rwd_all", "bookings_rwd_all", "availability_r"], address="8.8.8.8")
    bk._BACKOFF.clear()
    def respond(request):
        state.calls.append(request)
        if state.response_hook:
            state.response_hook(request)
        assert request.url.host == "api.bookeo.com" and request.url.scheme == "https"
        assert not {"secretKey", "apiKey", "access_token", "mode"} & set(request.url.params)
        if "authorization" not in request.headers:
            assert request.headers["X-Bookeo-secretKey"] == CREDS["secret_key"]
            assert request.headers["X-Bookeo-apiKey"] == CREDS["api_key"]
        if state.override:
            response = state.override(request)
            if response is not None:
                return response
        path = request.url.path
        if path == "/v2/settings/business":
            return httpx.Response(200, json={"id": state.account, "name": "Fixture Business", "emailAddress": "private@example.test"})
        if path == "/v2/settings/apikeyinfo":
            return httpx.Response(200, json={"accountId": state.account, "permissions": state.permissions, "creationTime": "2026-10-06T09:00:00Z"})
        if request.method == "DELETE":
            return httpx.Response(204)
        if path.startswith("/v2/customers"):
            row = deepcopy(CUSTOMER)
        elif path.startswith("/v2/bookings"):
            row = deepcopy(BOOKING)
        elif path.endswith("products"):
            row = deepcopy(PRODUCT)
        elif path.endswith("resources"):
            row = {"id": "guides", "name": "Guides", "isPublic": True, "resources": [{"id": "guide42", "name": "Fixture Guide", "password": "private-field"}]}
        elif path.endswith("peoplecategories"):
            return httpx.Response(200, json={"categories": [{"id": "adult", "name": "Adults", "numSeats": 1}]})
        elif path.endswith("languages"):
            return httpx.Response(200, json={"data": [{"tag": "en-US", "name": "English", "customersDefault": True}]})
        else:
            row = {"productId": "product42", "eventId": "event42", "startTime": WINDOW["start_time"], "endTime": WINDOW["end_time"], "numSeatsAvailable": 3}
        if request.method in {"POST", "PUT"}:
            return httpx.Response(201 if request.method == "POST" else 200, json=row, headers={"Location": "https://api.bookeo.com/private?apiKey=" + CREDS["api_key"]})
        if path.count("/") == 3 and not path.startswith("/v2/settings/") and not path.startswith("/v2/availability/"):
            return httpx.Response(200, json=row)
        return httpx.Response(200, json={"data": [row], "info": {"currentPage": 1, "totalPages": 1, "totalItems": 1}})
    async def dns(*a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (state.address, 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    original = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(bk, "guarded_async_client", client)
    return state


CASES = [
    ("get_business", {}, "/settings/apikeyinfo", "GET"), ("get_key_permissions", {}, "/settings/apikeyinfo", "GET"),
    ("list_products", {}, "/settings/products", "GET"), ("list_resources", {}, "/settings/resources", "GET"),
    ("list_people_categories", {}, "/settings/peoplecategories", "GET"), ("list_languages", {}, "/settings/languages", "GET"),
    ("list_availability", {**WINDOW, "product_id": "product42"}, "/availability/slots", "GET"),
    ("list_customers", {}, "/customers", "GET"), ("get_customer", {"customer_id": "customer42"}, "/customers/customer42", "GET"),
    ("create_customer", {"first_name": "Fixture", "last_name": "Customer"}, "/customers", "POST"),
    ("update_customer", {"customer_id": "customer42", "first_name": "Changed", "last_name": "Customer"}, "/customers/customer42", "PUT"),
    ("delete_customer", {"customer_id": "customer42"}, "/customers/customer42", "DELETE"),
    ("list_bookings", WINDOW, "/bookings", "GET"), ("get_booking", {"booking_number": "000042"}, "/bookings/000042", "GET"),
    ("create_booking", {**WINDOW, "product_id": "product42", "customer_id": "customer42", "event_id": "event42", "people_numbers": [{"people_category_id": "adult", "number": 1}]}, "/bookings", "POST"),
    ("cancel_booking", {"booking_number": "000042"}, "/bookings/000042", "DELETE"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,path,method", CASES)
async def test_actual_factory_run_and_wire_every_native_action(wire, op, args, path, method):
    node = factory(op, args)
    assert isinstance(node, bk.BookeoNode)
    result = await node.run({})
    assert result["account_id"] == "account42"
    assert wire.calls[-1].url.path == "/v2" + path and wire.calls[-1].method == method
    text = json.dumps(result)
    for private in (*CREDS.values(), "private@example.test", "PrivateName", "private-phone", "private-field", "apiKey=", '"price"', '"credit"'):
        if private != "account42":
            assert private not in text
    if op == "create_booking":
        assert result["data"]["accepted"] is False
        assert dict(wire.calls[-1].url.params) == {"notifyUsers": "false", "notifyCustomer": "false", "sendCustomerReminders": "false", "sendCustomerThankyou": "false"}
        body = json.loads(wire.calls[-1].content)
        assert body == {"productId": "product42", "customerId": "customer42", "eventId": "event42", "participants": {"numbers": [{"peopleCategoryId": "adult", "number": 1}]}}
    if op == "cancel_booking":
        assert result["canceled"] is True and result["bookingNumber"] == "000042"
        assert all(v == "false" for v in wire.calls[-1].url.params.values())
        assert wire.calls[-1].url.params["applyCancellationPolicy"] == "false"
    if op == "update_customer":
        body = json.loads(wire.calls[-1].content)
        assert body["phoneNumbers"] == CUSTOMER["phoneNumbers"] and "credit" not in body and "id" not in body


def test_real_shape_three_values_omitted_defaults_and_actual_native_class():
    blob, errors, resolved = cc.shape_credential(FAMILY, {"secret_key": CREDS["secret_key"], "api_key": CREDS["api_key"]})
    assert errors == {} and resolved == (TYPE, bk.BookeoAPIKeyCredential)
    assert blob == {"secret_key": CREDS["secret_key"], "api_key": CREDS["api_key"]}
    schema = bk.BookeoNodeConfig.model_json_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 16


@pytest.mark.asyncio
async def test_people_categories_use_provider_categories_envelope(wire):
    result = await factory("list_people_categories").run({})
    assert result["data"] == [{"id": "adult", "name": "Adults", "numSeats": 1}]
    wire.override = lambda request: httpx.Response(200, json={"data": []}) if request.url.path.endswith("peoplecategories") else None
    with pytest.raises(ValueError, match="settings list is invalid"):
        await factory("list_people_categories").run({})


@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign_api_key"])
def test_original_wrong_or_present_null_family_rejected(tag):
    with pytest.raises(ValueError, match="native Bookeo"):
        factory("get_business", credential={**CREDS, "credential_type": tag})
    assert bk.BookeoNode.validate_config({"config": {"operation": "get_business"}, "credentials": {**CREDS, "credential_type": tag}})["valid"] is False


@pytest.mark.parametrize("sidecar", [{"endpoint": "https://foreign.example.test"}, {"headers": {"Authorization": "foreign"}}, {"notifyCustomer": True}, {"initialPayments": [{"amount": 1}]}, {"mode": "backend"}])
def test_typed_factory_denies_unknown_transport_and_effect_fields(sidecar):
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("list_customers", sidecar)


@pytest.mark.asyncio
async def test_account_permissions_and_parent_denials_precede_mutation(wire):
    wire.account = "foreign"
    with pytest.raises(ValueError, match="different account"):
        await factory("delete_customer", {"customer_id": "customer42"}).run({})
    assert len(wire.calls) == 1
    wire.account, wire.calls = "account42", []
    wire.permissions = ["customers_r_all"]
    with pytest.raises(ValueError, match="lacks"):
        await factory("delete_customer", {"customer_id": "customer42"}).run({})
    assert len(wire.calls) == 2


@pytest.mark.asyncio
async def test_signed_navigation_uses_only_token_and_page_and_preserves_filter_binding(wire):
    client = bk._Client(bk._Authority(CREDS))
    await client.identity()
    def page(request):
        n = int(request.url.params.get("pageNumber", 1))
        return httpx.Response(200, json={"data": [CUSTOMER], "info": {"totalItems": 2, "totalPages": 2, "currentPage": n, "pageNavigationToken": "opaque=nav+value"}})
    wire.override = page
    first = await client.page("customers", "/customers", {"itemsPerPage": 50})
    with pytest.raises(ValueError, match="another credential"):
        await client.page("customers", "/customers", {"itemsPerPage": 100}, first["next_page_token"])
    second = await client.page("customers", "/customers", {"itemsPerPage": 50}, first["next_page_token"])
    assert second["next_page_token"] is None
    assert dict(wire.calls[-1].url.params) == {"pageNavigationToken": "opaque=nav+value", "pageNumber": "2"}


@pytest.mark.asyncio
async def test_public_dns_enforced_even_with_legacy_override(wire, monkeypatch):
    wire.address = "169.254.169.254"
    with pytest.raises(ValueError, match="non-public"):
        await factory("get_business").run({})
    assert wire.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 202, 302])
async def test_safe_error_body_no_retry_or_secret_url(wire, status):
    wire.override = lambda req: httpx.Response(status, json={"message": CREDS["secret_key"]}, headers={"Retry-After": "7"})
    with pytest.raises(ValueError) as error:
        await factory("get_business").run({})
    assert CREDS["secret_key"] not in str(error.value) and len(wire.calls) == 1
    if status == 429:
        assert "7 seconds" in str(error.value)
        with pytest.raises(ValueError, match="still throttled"):
            await factory("get_business").run({})
        assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_supplied_bearer_expiry_and_distinct_key_info_contract(wire):
    bearer = {"access_token": "synthetic-bookeo-bearer-token", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "expected_account_id": "account42"}
    result = await factory("get_business", credential=bearer).run({})
    assert result["account_id"] == "account42" and len(wire.calls) == 1
    assert wire.calls[0].headers["Authorization"] == "Bearer " + bearer["access_token"]
    with pytest.raises(ValueError, match="API key credential"):
        await factory("get_key_permissions", credential=bearer).run({})
    assert len(wire.calls) == 1
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("get_business", credential={**bearer, "expires_at": "2000-01-01T00:00:00Z"})
