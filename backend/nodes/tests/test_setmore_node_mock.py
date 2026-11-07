"""Setmore factory, transport, token exchange, parsing and picker regressions."""
from copy import deepcopy
import ipaddress
import json
import logging
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from nodes import setmore_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import validate_for_connect
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation

NODE, FAMILY = native.NODE_TYPE, "setmore_refresh_token"
CID, USER, ORG, OWNER, WORKFLOW = (str(UUID(int=i)) for i in (42, 1, 3, 2, 4))
CREDS = {"credential_type": FAMILY, "refresh_token": "synthetic-refresh-42+opaque/value"}
ACCESS = "synthetic-access-token-42"
OPS = {"list_services", "list_categories", "list_category_services", "list_staff", "get_slots", "find_customers", "create_customer", "list_appointments", "create_appointment", "update_appointment_label"}
SERVICE = {"key": "service_42", "service_name": "Fixture service", "staff_keys": ["staff_42"], "duration": 30, "buffer_duration": 0, "cost": 300, "image_url": "private-image", "description": "private-description"}
STAFF = {"key": "staff_42", "first_name": "Fixture", "last_name": "Staff", "email_id": "private@example.invalid", "comment": "private-comment"}
CUSTOMER = {"key": "customer_42", "first_name": "Fixture", "email_id": "private@example.invalid", "additional_fields": {"private": "private-custom"}}
APPOINTMENT = {"key": "appointment_42", "staff_key": "staff_42", "service_key": "service_42", "customer_key": "customer_42", "start_time": "2026-10-07T09:00Z", "end_time": "2026-10-07T09:30Z", "label": "Fixture", "cost": 300, "comment": "private-comment", "video_meeting_url": "private-video", "customer": CUSTOMER}
BOOKING = {"staff_key": "staff_42", "service_key": "service_42", "customer_key": "customer_42", "start_time": "2026-10-07T09:00Z", "end_time": "2026-10-07T09:30Z", "confirm_booking": True}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def provider(monkeypatch):
    from utils import ssrf
    state = SimpleNamespace(requests=[], status=200, override=None, token_override=None, raw=None, headers={}, timeout=False, after_response=None, services=[deepcopy(SERVICE)], staff=[deepcopy(STAFF)])
    original_dns, original_client = ssrf._resolve_host_addresses, ssrf.guarded_async_client
    async def public_dns(host, port, **kwargs):
        assert kwargs.get("permit_non_public", False) is False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            assert host == "developer.setmore.com"
            return ["93.184.216.34"]
        return await original_dns(host, port, **kwargs)
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", public_dns)
    async def respond(request):
        assert request.url.scheme == "https" and request.url.host == "developer.setmore.com"
        state.requests.append(request)
        if state.timeout:
            raise httpx.ReadTimeout("private URL " + CREDS["refresh_token"], request=request)
        exchange = request.url.path == "/api/v1/o/oauth2/token"
        if exchange:
            assert request.method == "GET" and dict(request.url.params) == {"refreshToken": CREDS["refresh_token"]}
            assert "authorization" not in request.headers and not request.content
            envelope = {"response": True, "data": {"token": {"access_token": ACCESS, "token_type": "BEARER", "expires_in": 3600, "user_id": "opaque-private-user"}}}
            if state.token_override is not None:
                envelope = deepcopy(state.token_override)
        else:
            assert request.headers["authorization"] == "Bearer " + ACCESS
            assert CREDS["refresh_token"] not in str(request.url) and "refreshToken" not in request.url.params
            path = request.url.path.removeprefix("/api/v1/bookingapi")
            assert path != request.url.path
            if path in ("/services", "/services/categories/category_42"):
                data = {"services": deepcopy(state.services)}
            elif path == "/services/categories":
                data = {"service_categories": [{"key": "category_42", "categoryName": "Fixture category", "serviceIdList": ["service_42"], "deleteFlag": False}]}
            elif path == "/staffs": data = {"staffs": deepcopy(state.staff), "cursor": "unconsumed-staff-cursor"}
            elif path == "/slots": data = {"slots": {"2026-10-07": ["9:00 AM", "9:30 AM"]}}
            elif path == "/customer": data = {"customer": [deepcopy(CUSTOMER)]}
            elif path == "/customer/create":
                customer = deepcopy(CUSTOMER)
                customer.update(json.loads(request.content))
                data = {"customer": customer}
            elif path == "/appointments": data = {"appointments": [deepcopy(APPOINTMENT)], "cursor": "provider-cursor"}
            elif path == "/appointment/create":
                appointment = deepcopy(APPOINTMENT)
                appointment.update(json.loads(request.content))
                data = {"appointment": appointment}
            elif path == "/appointments/appointment_42/label":
                data = {"appointment": {**APPOINTMENT, "label": request.url.params["label"]}}
                assert request.method == "PUT" and not request.content
            else: raise AssertionError("Undeclared Setmore endpoint")
            envelope = {"response": True, "data": data}
            if state.override is not None:
                envelope = state.override(request, envelope) if callable(state.override) else deepcopy(state.override)
        if state.after_response:
            state.after_response()
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


def test_actual_factory_catalog_and_manual_refresh_family():
    from coder.workflow.operation_catalog import get_operations_for_node_type, node_accepted_credential_types
    assert NODE_REGISTRY[NODE] is native.SetmoreNode
    assert {op.name for op in get_operations_for_node_type(NODE)} == OPS
    assert node_accepted_credential_types(NODE) == {FAMILY}
    instance = NodeFactory.create_node("fixture", NODE, {"config": {"operation": "list_services"}, "credentials": CREDS}, user_id=USER)
    assert isinstance(instance.config, native.SetmoreNodeConfig)
    model = native.SetmoreRefreshTokenCredential.model_json_schema()
    assert model["properties"]["refresh_token"]["ui:widget"] == "password"
    assert "x-oauth-provider" not in model and "x-credential-type" not in model


@pytest.mark.parametrize("family", [None, "", "foreign", "setmore_oauth", "bearer_token"])
def test_explicit_family_precedes_manual_shape(family):
    with pytest.raises(ValueError):
        native.SetmoreNode.parse_config({"config": {"operation": "list_services"}, "credentials": {**CREDS, "credential_type": family}})


@pytest.mark.parametrize("secret", ["your-refresh-token", "<refresh_token>", "https://secret.example", "Bearer abc", "a\nb", "abc ", "a\x7fb"])
def test_credentials_hide_rejected_secret(secret):
    with pytest.raises(ValueError) as error:
        native.SetmoreRefreshTokenCredential(refresh_token=secret)
    assert secret not in str(error.value) and CREDS["refresh_token"] not in repr(native.SetmoreRefreshTokenCredential(**CREDS))


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,method,path", [
    ("list_services", {}, "GET", "/services"), ("list_categories", {}, "GET", "/services/categories"),
    ("list_category_services", {"category_key": "category_42"}, "GET", "/services/categories/category_42"),
    ("list_staff", {}, "GET", "/staffs"), ("get_slots", {"staff_key": "staff_42", "service_key": "service_42", "selected_date": "07/10/2026"}, "POST", "/slots"),
    ("find_customers", {"firstname": "Fixture", "email": "private@example.invalid"}, "GET", "/customer"),
    ("create_customer", {"first_name": "Fixture", "email_id": "private@example.invalid"}, "POST", "/customer/create"),
    ("list_appointments", {"start_date": "07-10-2026", "end_date": "08-10-2026", "cursor": "original-cursor"}, "GET", "/appointments"),
    ("create_appointment", BOOKING, "POST", "/appointment/create"),
    ("update_appointment_label", {"appointment_key": "appointment_42", "label": "Follow up"}, "PUT", "/appointments/appointment_42/label"),
])
async def test_exact_native_route_contracts_and_private_projection(provider, op, args, method, path):
    result = await run(op, args)
    assert result["status"] == "success"
    assert provider.requests[0].url.path == "/api/v1/o/oauth2/token"
    assert sum(r.url.path.endswith("/o/oauth2/token") for r in provider.requests) == 1
    last = provider.requests[-1]
    assert last.method == method and last.url.path == "/api/v1/bookingapi" + path
    for private in (CREDS["refresh_token"], ACCESS, "opaque-private-user", "private-image", "private-comment", "private-custom", "private-video", "private@example.invalid"):
        assert private not in json.dumps(result)
    if op == "list_appointments":
        assert dict(last.url.params) == {"startDate": "07-10-2026", "endDate": "08-10-2026", "customerDetails": "false", "cursor": "original-cursor"}
        assert result["data"]["next_cursor"] == "provider-cursor"
    if op == "create_appointment":
        assert "confirm_booking" not in json.loads(last.content)
        assert result["data"]["notifications_possible"] is True
    if op == "get_slots": assert result["data"]["booking_created"] is False


@pytest.mark.asyncio
async def test_cursor_on_empty_page_and_no_guessed_staff_cursor(provider):
    provider.override = {"response": True, "data": {"appointments": [], "cursor": "continue-even-empty"}}
    result = await run("list_appointments", {"start_date": "07-10-2026", "end_date": "08-10-2026"})
    assert result["data"]["items"] == [] and result["data"]["next_cursor"] == "continue-even-empty"
    provider.override = None
    result = await run("list_staff")
    assert result["data"]["provider_cursor"] == "unconsumed-staff-cursor" and result["data"]["next_cursor"] is None
    assert not provider.requests[-1].url.params


@pytest.mark.asyncio
async def test_staff_service_association_before_slots_or_booking(provider):
    provider.services[0]["staff_keys"] = ["other_staff"]
    with pytest.raises(ValueError, match="associated"):
        await run("create_appointment", BOOKING)
    assert all(request.method == "GET" for request in provider.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args", [("get_slots", {"service_key": "../evil", "staff_key": "staff_42", "selected_date": "07/10/2026"}), ("get_slots", {"service_key": "service_42", "staff_key": "staff_42", "selected_date": "31/02/2026"}), ("find_customers", {}), ("create_appointment", {**BOOKING, "confirm_booking": False}), ("create_appointment", {**BOOKING, "end_time": BOOKING["start_time"]}), ("list_appointments", {"start_date": "07-10-2026", "end_date": "08-12-2026"}), ("cancel_appointment", {}), ("delete_customer", {})])
async def test_invalid_or_undeclared_actions_stop_before_exchange(provider, op, args):
    with pytest.raises(ValueError): await run(op, args)
    assert provider.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_private_transport_errors_and_no_retry(provider, status, caplog):
    provider.status = status
    with caplog.at_level(logging.DEBUG), pytest.raises(ValueError) as error:
        await run("list_services")
    assert len(provider.requests) == 1
    assert CREDS["refresh_token"] not in str(error.value) + caplog.text and "refreshToken=" not in caplog.text


@pytest.mark.asyncio
async def test_http200_provider_errors_and_token_envelope_are_not_evidence(provider):
    provider.token_override = {"response": True, "msg": "invalid firstname", "error": "invalid_request"}
    result = await collect_evidence(node_type=NODE, credential_data=CREDS, user_id=USER)
    assert result.reachable is None and len(provider.requests) == 1
    provider.token_override = None
    provider.override = {"response": True, "error": "invalid_request", "msg": "Slot is already booked"}
    with pytest.raises(ValueError): await run("create_appointment", BOOKING)
    provider.override = {"response": False, "error": "unauthorized_request"}
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER)
    assert verdict.ok is False and verdict.evidence.reachable is False


@pytest.mark.asyncio
async def test_actual_connect_collector_and_picker_use_protected_account_data(provider):
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True
    assert verdict.evidence.samples[0].label == SERVICE["service_name"] and verdict.evidence.account_label is None
    options = await native.SetmoreNode.load_field_options("staff_key", CREDS, {"service_key": "service_42"}, search="fixture")
    assert options == {"options": [{"value": "staff_42", "label": "Fixture Staff"}], "next_page_token": None}
    provider.services = []
    evidence = await collect_evidence(node_type=NODE, credential_data=CREDS, user_id=USER)
    assert evidence.reachable is True and evidence.samples == [] and evidence.account_label is None


@pytest.mark.asyncio
async def test_freshen_preserves_permanent_token_and_picker_exchanges_before_use(provider):
    credential = {**CREDS, "access_token": "stale-bearer", "expires_at": "2000-01-01T00:00:00Z", "token_version": 7}
    original = deepcopy(credential)
    freshened = await native.SetmoreNode.freshen_credential(
        credential, pool=object(), user_id=USER, credential_id=CID,
    )
    assert freshened is credential and freshened == original
    assert provider.requests == []  # No permanent-token rotation or persistence.

    options = await native.SetmoreNode.load_field_options("service_key", freshened)
    assert options["options"] == [{"value": SERVICE["key"], "label": SERVICE["service_name"]}]
    assert [request.url.path for request in provider.requests] == [
        "/api/v1/o/oauth2/token", "/api/v1/bookingapi/services",
    ]
    assert provider.requests[-1].headers["authorization"] == "Bearer " + ACCESS


@pytest.mark.asyncio
async def test_freshen_validates_native_credential_without_http(provider):
    assert await native.SetmoreNode.freshen_credential(None) is None
    for credential in ({**CREDS, "credential_type": "foreign"}, {**CREDS, "refresh_token": "<refresh_token>"}):
        with pytest.raises(ValueError):
            await native.SetmoreNode.freshen_credential(credential)
    assert provider.requests == []


@pytest.mark.asyncio
async def test_response_bounds_media_duplicate_properties_and_ack_binding(provider):
    provider.headers = {"content-type": "text/html"}
    with pytest.raises(ValueError): await run("list_services")
    provider.headers = {}
    provider.raw = b'{"response":true,"response":true,"data":{}}'
    with pytest.raises(ValueError): await run("list_services")
    provider.raw = b" " * (native.MAX_BYTES + 1)
    with pytest.raises(ValueError): await run("list_services")
    provider.raw = None
    provider.override = {"response": True, "data": {"appointment": {**APPOINTMENT, "key": "wrong_appointment"}}}
    with pytest.raises(ValueError): await run("update_appointment_label", {"appointment_key": "appointment_42", "label": "Fixture"})
    provider.override = {"response": True, "data": {"services": [{**SERVICE, "service_name": CREDS["refresh_token"]}]}}
    with pytest.raises(ValueError): await run("list_services")


@pytest.mark.parametrize("value", [False, 0, 1, "true"])
def test_booking_confirmation_is_not_truthy_coercion(value):
    with pytest.raises(ValueError): native.SetmoreCreateAppointmentConfig(**{**BOOKING, "confirm_booking": value})
