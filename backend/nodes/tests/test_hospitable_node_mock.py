"""Hospitable contract routing, body serialization and credential regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import hospitable_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-hospitable-test-token"
PROPERTY = "12345678-1234-4234-8234-123456789abc"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="hospitable-fixture", node_type="automation-hospitable",
        node_data={"config": config, "credentials": credential or {"credential_type": "hospitable_api_token", "api_token": TOKEN}})


def transport(monkeypatch, *, status=200, body=None, content=None):
    calls = []
    def respond(request):
        calls.append(request)
        if content is not None:
            return httpx.Response(status, content=content, headers={"Content-Type": "text/html"})
        return httpx.Response(status, json=body if body is not None else {"data": {"id": PROPERTY}})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


# Independent expected methods and paths, taken from the pinned v2 contract.
CASES = [
    ("get_user", {}, "GET", "/user", 200),
    ("list_properties", {}, "GET", "/properties", 200),
    ("get_property", {"property_id": PROPERTY}, "GET", f"/properties/{PROPERTY}", 200),
    ("get_calendar", {"property_id": PROPERTY, "start_date": "2026-07-10", "end_date": "2026-07-12"}, "GET", f"/properties/{PROPERTY}/calendar", 200),
    ("update_calendar", {"property_id": PROPERTY, "dates": [{"date": "2026-07-10", "available": False, "price": {"amount": 1000}, "note": None}]}, "PUT", f"/properties/{PROPERTY}/calendar", 202),
    ("list_reservations", {"properties": [PROPERTY]}, "GET", "/reservations", 200),
    ("create_reservation", {"property_id": PROPERTY, "guests": {"adults": 2}, "check_in": "2026-07-10", "check_out": "2026-07-12", "guest": {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"}, "financials": {"accommodation": 30000, "currency": "USD"}, "language": "en"}, "POST", "/reservations", 201),
    ("get_reservation", {"reservation_id": "ABC-123"}, "GET", "/reservations/ABC-123", 200),
    ("cancel_reservation", {"reservation_id": PROPERTY}, "POST", f"/reservations/{PROPERTY}/cancel", 200),
    ("list_reservation_messages", {"reservation_id": PROPERTY}, "GET", f"/reservations/{PROPERTY}/messages", 200),
    ("send_reservation_message", {"reservation_id": PROPERTY, "body": "Welcome!"}, "POST", f"/reservations/{PROPERTY}/messages", 202),
    ("list_inquiries", {"properties": [PROPERTY]}, "GET", "/inquiries", 200),
    ("get_inquiry", {"inquiry_id": PROPERTY}, "GET", f"/inquiries/{PROPERTY}", 200),
    ("send_inquiry_message", {"inquiry_id": PROPERTY, "body": "Yes, those dates are available."}, "POST", f"/inquiries/{PROPERTY}/messages", 202),
    ("list_tasks", {"properties": [PROPERTY]}, "GET", "/tasks", 200),
    ("create_task", {"property_id": PROPERTY, "task_type": 1, "start_date": "2026-05-18T12:15:00-04:00", "end_date": "2026-05-18T17:00:00-04:00"}, "POST", "/tasks", 200),
    ("get_task", {"task_id": PROPERTY}, "GET", f"/tasks/{PROPERTY}", 200),
    ("update_task", {"task_id": PROPERTY, "note": None, "teammate_uuid": None}, "PATCH", f"/tasks/{PROPERTY}", 200),
    ("delete_task", {"task_id": PROPERTY}, "DELETE", f"/tasks/{PROPERTY}", 200),
    ("list_teammates", {}, "GET", "/teammates", 200),
    ("list_reviews", {"property_id": PROPERTY}, "GET", f"/properties/{PROPERTY}/reviews", 200),
    ("respond_review", {"review_id": PROPERTY, "response": "Thank you for staying!"}, "POST", f"/reviews/{PROPERTY}/respond", 200),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,status", CASES, ids=[c[0] for c in CASES])
async def test_hospitable_all_operations(monkeypatch, operation, config, method, path, status):
    calls = transport(monkeypatch, status=status)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert result["accepted"] is (status == 202)
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.scheme == "https" and request.url.host == "public.api.hospitable.com"
    assert request.url.path == "/v2" + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result) and TOKEN not in str(request.url)
    if method in {"POST", "PUT", "PATCH"}:
        body = json.loads(request.content)
        expected = {k: v for k, v in config.items() if k not in {"reservation_id", "inquiry_id", "task_id", "review_id"}}
        if operation == "update_calendar":
            expected.pop("property_id")
        if operation == "cancel_reservation":
            expected["initiated_by"] = "host"
        assert body == expected
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_repeated_property_filters_and_explicit_pagination(monkeypatch):
    payload = {"data": [], "meta": {"current_page": 2, "last_page": 3}, "links": {"next": "https://public.api.hospitable.com/v2/reservations?page=3"}}
    calls = transport(monkeypatch, body=payload)
    result = await node({"operation": "list_reservations", "properties": [PROPERTY, "second-property"], "page": 2, "per_page": 50, "statuses": ["accepted", "request"], "platforms": ["airbnb"]}).execute({})
    assert calls[0].url.params.get_list("properties[]") == [PROPERTY, "second-property"]
    assert calls[0].url.params.get_list("status[]") == ["accepted", "request"]
    assert calls[0].url.params.get("platforms[]") == "airbnb"
    assert calls[0].url.params.get("page") == "2"
    assert result["data"] == payload and len(calls) == 1


@pytest.mark.asyncio
async def test_task_patch_omission_and_null_distinct(monkeypatch):
    calls = transport(monkeypatch)
    await node({"operation": "update_task", "task_id": PROPERTY, "note": "Ready", "send_task_reminder": False}).execute({})
    assert json.loads(calls[0].content) == {"note": "Ready", "send_task_reminder": False}


@pytest.mark.asyncio
async def test_documented_accepted_calendar_response(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/hospitable/calendar_accepted.json").read_text())
    transport(monkeypatch, status=202, body=fixture)
    result = await node({"operation": "update_calendar", "property_id": PROPERTY, "dates": [{"date": "2026-07-10", "available": False}]}).execute({})
    assert result["accepted"] is True and result["data"] == {"status": "accepted"}


@pytest.mark.asyncio
async def test_empty_delete_success(monkeypatch):
    transport(monkeypatch, content=b"")
    assert (await node({"operation": "delete_task", "task_id": PROPERTY}).execute({}))["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_provider_rejections_preserve_words_redact_token_no_retry(monkeypatch, status):
    calls = transport(monkeypatch, status=status, body={"message": "Token refused: " + TOKEN})
    result = await node({"operation": "get_user"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Token refused: [redacted]" and len(calls) == 1


@pytest.mark.asyncio
async def test_html_success_is_not_connection_evidence(monkeypatch):
    transport(monkeypatch, content=b"<html>Sign in</html>")
    with pytest.raises(ValueError, match="JSON"):
        await node({"operation": "get_user"}).execute({})


@pytest.mark.parametrize("token", ["", "Bearer abc", "https://example.com/token", "<token>", "bad\r\nheader", "not\u200ba-token"])
def test_invalid_credentials(token):
    with pytest.raises(ValidationError):
        native.HospitableTokenCredential(api_token=token)


def test_manual_token_type_default_and_shaping():
    value = native.HospitableTokenCredential(api_token="  " + TOKEN + "\n")
    assert value.credential_type == "hospitable_api_token" and value.api_token == TOKEN
    assert TOKEN not in repr(value)


@pytest.mark.parametrize("config", [
    {"operation": "get_property", "property_id": "../user"},
    {"operation": "get_task", "task_id": "42?include=secrets"},
    {"operation": "list_tasks", "properties": []},
    {"operation": "list_reviews", "property_id": PROPERTY, "per_page": 51},
    {"operation": "update_task", "task_id": PROPERTY},
    {"operation": "create_task", "property_id": PROPERTY, "task_type": 6},
])
def test_invalid_operations(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_documented_property_example_parses_despite_provider_schema_conflict(monkeypatch):
    payload = json.loads((Path(__file__).parent / "fixtures/hospitable/property_documented.json").read_text())
    transport(monkeypatch, body=payload)
    result = await node({"operation": "get_property", "property_id": payload["id"]}).execute({})
    assert result["status"] == "success" and result["data"] == payload
    assert result["data"]["address"]["coordinates"]["latitude"] == 50.8514786
