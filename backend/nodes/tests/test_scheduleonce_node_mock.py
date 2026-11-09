"""Offline request and response tests for the Scheduleonce workflow node.

Official response examples pin scheduling and contact behavior without any live account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import scheduleonce_node as native
from nodes.core.registry import NodeFactory

TOKEN = "scheduleonce-fixture-secret-728"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/scheduleonce/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="scheduleonce-fixture", node_type="automation-scheduleonce",
        node_data={"config": config, "credentials": {"api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    real_client = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


READS = [
    ("list_bookings", "/bookings"), ("get_booking", "/bookings/BKNG-123"),
    ("list_booking_calendars", "/booking-calendars"), ("get_booking_calendar", "/booking-calendars/BKC-123"),
    ("list_booking_pages", "/booking-pages"), ("get_booking_page", "/booking-pages/BKP-123"),
    ("list_event_types", "/event-types"), ("get_event_type", "/event-types/EVT-123"),
    ("list_users", "/users"), ("get_user", "/users/USR-123"),
    ("list_contacts", "/contacts"), ("get_contact", "/contacts/CTC-123"),
    ("list_teams", "/teams"), ("get_team", "/teams/TM-123"),
    ("check_connection", "/test"), ("get_time_slots", "/booking-calendars/BKC-123/time-slots"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", READS)
async def test_reads_auth_paths_and_one_page(monkeypatch, operation, path):
    config = {"operation": operation}
    if operation.startswith("get_"):
        config["id"] = path.split("/")[2]
    body = {"object": "list", "data": [{"id": "USR-owned", "email": "owner@example.com"}], "has_more": True} if operation.startswith("list_") else EXAMPLES.get(operation, {"id": "owned"})
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(requests) == 1
    req = requests[0]
    assert req.method == "GET" and req.url.path == "/v2" + path
    assert req.url.host == "api.oncehub.com" and req.headers["API-Key"] == TOKEN
    assert not req.content and TOKEN not in str(result)
    if operation.startswith("list_"):
        assert dict(req.url.params) == {"limit": "10"}
        assert result["has_more"] and result["next_after"] == "USR-owned"


WRITES = [
    ({"operation": "cancel_booking", "id": "BKNG-123", "cancellation_reason": "Changed plans", "send_cancellation_email": False}, "POST", "/bookings/BKNG-123/cancel", {"cancellation_reason": "Changed plans", "send_cancellation_email": False}),
    ({"operation": "request_reschedule", "id": "BKNG-123", "reschedule_reason": "New date"}, "POST", "/bookings/BKNG-123/request-reschedule", {"reschedule_reason": "New date"}),
    ({"operation": "reassign_booking", "id": "BKNG-123", "new_host": "USR-456"}, "POST", "/bookings/BKNG-123/reassign", {"new_host": "USR-456"}),
    ({"operation": "mark_no_show", "id": "BKNG-123"}, "POST", "/bookings/BKNG-123/no-show", None),
    ({"operation": "schedule_booking", "id": "BKC-123", "start_time": "2024-12-02T06:30:00.000Z", "guest_time_zone": "America/New_York", "booking_form": {"name": "Carrie Customer", "email": "carrie.customer@gmail.com"}}, "POST", "/booking-calendars/BKC-123/schedule", {"start_time": "2024-12-02T06:30:00.000Z", "guest_time_zone": "America/New_York", "booking_form": {"name": "Carrie Customer", "email": "carrie.customer@gmail.com"}}),
    ({"operation": "create_one_time_link", "id": "BKC-123", "hide_url_params": False, "booking_form": {"name": "Carrie Customer", "email": "carrie.customer@example.com"}}, "POST", "/booking-calendars/BKC-123/one-time-links", {"hide_url_params": False, "booking_form": {"name": "Carrie Customer", "email": "carrie.customer@example.com"}}),
    ({"operation": "create_contact", "first_name": "Carrie", "last_name": "Customer", "email": "carrie.customer@gmail.com"}, "POST", "/contacts", {"first_name": "Carrie", "last_name": "Customer", "email": "carrie.customer@gmail.com"}),
    ({"operation": "update_contact", "id": "CTC-123", "company": "Acme Inc", "has_consent": False, "employees": 0}, "PATCH", "/contacts/CTC-123", {"company": "Acme Inc", "has_consent": False, "employees": 0}),
    ({"operation": "delete_contact", "id": "CTC-123"}, "DELETE", "/contacts/CTC-123", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,expected_body", WRITES)
async def test_writes_exact_body_no_retry_and_documented_responses(monkeypatch, config, method, path, expected_body):
    body = EXAMPLES.get(config["operation"], {"id": config.get("id", "CTC-123")})
    requests = transport(monkeypatch, body, 201 if config["operation"] == "create_contact" else 200)
    result = await node(config).execute({})
    assert result["data"] == body and len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == "/v2" + path
    assert (json.loads(req.content) if req.content else None) == expected_body


@pytest.mark.asyncio
async def test_query_alias_pagination_and_false_values(monkeypatch):
    requests = transport(monkeypatch, {"data": [], "has_more": False})
    result = await node({"operation": "list_bookings", "starting_time_gt": "2026-11-09", "after": "BKNG-456", "limit": 25}).execute({})
    assert dict(requests[0].url.params) == {"starting_time.gt": "2026-11-09", "after": "BKNG-456", "limit": "25"}
    assert result["next_after"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 409, 429, 500])
async def test_errors_redact_key_and_do_not_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"type": "invalid_request_error", "message": "Rejected " + TOKEN}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "cancel_booking", "id": "BKNG-123"}).execute({})
    assert "Rejected [redacted]" in str(exc.value) and TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_booking", "id": "../users"},
    {"operation": "get_booking", "id": "https://evil.test"},
    {"operation": "list_bookings", "after": "BKNG-123", "before": "BKNG-456"},
    {"operation": "list_users", "limit": 101},
    {"operation": "update_contact", "id": "CTC-123"},
    {"operation": "get_time_slots", "id": "BKC-123", "start_time": "2026-11-09T00:00:00Z", "end_time": "2026-12-10T00:00:00Z"},
])
def test_invalid_configuration_rejected(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_default_and_validation():
    assert native.ScheduleonceAPIKeyCredential(api_key=TOKEN).credential_type == "scheduleonce_api_key"
    for key in ["https://example.com/key", "<token>", "key\nInjected", "Bearer key"]:
        with pytest.raises(ValidationError):
            native.ScheduleonceAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": [], "has_more": True}, {"data": "wrong", "has_more": False}])
async def test_malformed_list_cannot_claim_connection(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_users"}).execute({})


@pytest.mark.asyncio
async def test_editor_credential_and_label_metadata_do_not_enter_request(monkeypatch):
    requests = transport(monkeypatch, {"id": "BKNG-123"})
    await node({"operation": "get_booking", "id": "BKNG-123", "id__label": "Owned booking",
        "credentialIds": {"scheduleonce_api_key": "saved-credential"}}).execute({})
    assert requests[0].url.path == "/v2/bookings/BKNG-123"
    assert not requests[0].url.params and not requests[0].content


def test_factory_validation_errors_never_show_secret():
    with pytest.raises(ValueError) as exc:
        NodeFactory.create_node(node_id="bad-key", node_type="automation-scheduleonce",
            node_data={"config": {"operation": "list_users"}, "credentials": {"api_key": TOKEN + " invalid"}})
    assert TOKEN not in str(exc.value)
