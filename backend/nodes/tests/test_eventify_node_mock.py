"""Offline request regressions against Eventify's published Admin API 4.0.1.

The fixtures retain provider-authored schema excerpts. Concrete inputs and
responses below are synthetic instances of those schemas, never live records.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import eventify_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-eventify-token-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {"credential_type": "eventify_session_token", "session_token": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="eventify-fixture", node_type="automation-eventify",
        node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,params", [
    ({"operation": "list_events"}, "/events", {}),
    ({"operation": "get_event", "eventid": 42}, "/events/42", {}),
    ({"operation": "list_attendees", "eventid": 42}, "/attendee", {"eventid": "42"}),
    ({"operation": "search_attendee", "eventid": 42, "searchtype": "email", "searchvalue": "person+event@example.com"}, "/attendee/search", {"eventid": "42", "searchtype": "email", "searchvalue": "person+event@example.com"}),
    ({"operation": "list_user_categories", "eventid": 42}, "/events/user_categories", {"eventid": "42"}),
    ({"operation": "list_interests", "eventid": 42}, "/events/interest", {"eventid": "42"}),
    ({"operation": "list_forms", "eventid": 42}, "/myForms", {"eventid": "42"}),
    ({"operation": "list_sessions"}, "/sessions", {}),
    ({"operation": "get_session", "sessionid": 7}, "/sessions/7", {}),
    ({"operation": "list_speakers", "eventid": 42}, "/speakers", {"eventid": "42"}),
    ({"operation": "get_speaker", "speakerid": 7}, "/speakers/7", {}),
    ({"operation": "list_exhibitors", "eventid": 42}, "/exhibitors", {"eventid": "42"}),
    ({"operation": "get_exhibitor", "exhibitorid": 7}, "/exhibitors/7", {}),
    ({"operation": "list_sponsors", "eventid": 42}, "/sponsors", {"eventid": "42"}),
    ({"operation": "get_sales_summary", "eventid": 42}, "/sales/summary", {"eventid": "42"}),
    ({"operation": "get_order", "eventid": 42, "ordernumber": 700}, "/sales/order-details", {"eventid": "42", "ordernumber": "700"}),
])
async def test_reads_use_exact_endpoint_and_query(monkeypatch, config, path, params):
    payload = [{"eventid": 42, "eventname": "Conference"}] if config["operation"] == "list_events" else {"resource": []}
    requests = transport(monkeypatch, payload)
    result = await node(config).execute({})
    assert result["data"] == payload
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.host == "adminapi.eventify.io"
    assert request.url.path == "/dev.php" + path
    assert dict(request.url.params) == {**params, "session_token": TOKEN}
    assert request.headers["User-Agent"] == "NoClick Eventify Integration"
    assert request.content == b""


@pytest.mark.asyncio
async def test_pagination_does_not_discard_envelope_or_auto_fetch(monkeypatch):
    payload = {"success": 1, "count": 32, "resource": [{"orderid": 7}, {"orderid": 8}], "invoice_base_url": "https://cdn.eventify.io/"}
    requests = transport(monkeypatch, payload)
    result = await node({"operation": "list_orders", "eventid": 42, "offset": 4, "limit": 2, "ticketid": "33"}).execute({})
    assert result["data"] == payload
    assert result["next_offset"] == 6
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {"eventid": "42", "ticketid": "33", "offset": "4", "limit": "2", "session_token": TOKEN}
    transport(monkeypatch, {"success": 1, "resource": []})
    result = await node({"operation": "list_orders", "eventid": 42}).execute({})
    assert result["next_offset"] is None


@pytest.mark.asyncio
async def test_create_attendee_uses_json_and_documented_null_links(monkeypatch):
    requests = transport(monkeypatch, {"is_error": 0, "message": "User Successfully Created", "userresponse": {"status_code": 200, "content": {"resource": []}}})
    config = {"operation": "create_attendee", "eventid": 42, "email": "person@example.com", "firstname": "Ada", "lastname": "Lovelace", "userpassword": "NewPass123", "form_number": 123456, "usercategory": "123,456,789", "details_form": [{"id": "bio", "value": "Biography"}, {"id": "section"}]}
    result = await node(config).execute({})
    request = requests[0]
    assert request.method == "POST" and request.url.path == "/dev.php/attendee"
    body = json.loads(request.content)
    assert body["eventid"] == 42 and body["email"] == config["email"]
    assert body["details_form"] == config["details_form"]
    assert all(body[k] is None for k in ["profileurl", "exhibitoridfk", "speakeridfk", "sponsoridfk"])
    assert body["sendwelcomeemail"] is False and body["isadmin"] == 0
    assert "operation" not in body and "session_token" not in body
    assert request.headers["content-type"] == "application/json"
    assert TOKEN not in str(result) and config["userpassword"] not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_attendee_patch_sends_only_changes_and_matching_form(monkeypatch):
    requests = transport(monkeypatch, [{"id": 7}])
    config = {"operation": "update_attendee", "userid": 7, "form_number": 123456, "details_form": '[{"id":"bio","value":"Biography"}]'}
    await node(config).execute({})
    assert requests[0].method == "PATCH" and requests[0].url.path == "/dev.php/attendee/7"
    assert json.loads(requests[0].content) == {k: v for k, v in config.items() if k not in {"operation", "userid"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,method,body", [
    ({"operation": "delete_attendee", "userid": 7}, "/attendee/7", "DELETE", None),
    ({"operation": "delete_session", "sessionid": 7}, "/sessions/7", "DELETE", None),
    ({"operation": "delete_speaker", "speakerid": 7}, "/speakers/7", "DELETE", None),
    ({"operation": "create_speaker", "eventid": 42, "firstname": "Ada", "lastname": "Lovelace"}, "/speakers", "POST", {"eventid": 42, "firstname": "Ada", "lastname": "Lovelace", "createuser": False}),
    ({"operation": "update_speaker", "eventid": 42, "speakerid": 7, "company": "Analytical Engines"}, "/speakers/7", "PATCH", {"eventid": 42, "speakerid": 7, "company": "Analytical Engines", "createuser": False}),
])
async def test_remaining_writes_preserve_ids_and_avoid_side_effects(monkeypatch, config, path, method, body):
    requests = transport(monkeypatch, [{"id": 7}])
    await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/dev.php" + path
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
async def test_session_create_is_one_flat_contract_operation(monkeypatch):
    config = {"operation": "create_session", "eventid": 42, "apptabid": 3, "scheduledateid": 4, "scheduletrackid": 5, "title": "Opening", "starttime": "2026-11-09 09:00:00", "endtime": "2026-11-09 10:00:00", "colorid": 6, "checkintype": "showqr", "sessiontype": "general"}
    requests = transport(monkeypatch, [{"id": 7}])
    await node(config).execute({})
    assert requests[0].method == "POST" and requests[0].url.path == "/dev.php/sessions"
    assert json.loads(requests[0].content) == {k: v for k, v in config.items() if k != "operation"}


@pytest.mark.asyncio
async def test_connect_uses_account_specific_event_names(monkeypatch):
    requests = transport(monkeypatch, [{"eventid": 42, "eventname": "Conference"}])
    result = await native.EventifyNode.load_field_options("eventid", credential())
    assert result == [{"value": "42", "label": "Conference"}]
    assert requests[0].url.path == "/dev.php/events"
    assert native.EventifyNode.connection_evidence.proves == "account"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(200, {"is_error": 1, "message": "Session expired"}), (401, {"message": "Invalid token"}), (403, {"message": TOKEN}), (200, {"success": 0, "message": "No access"}), (302, {"message": "Redirect"})])
async def test_errors_never_look_like_a_working_connection(monkeypatch, status, payload):
    requests = transport(monkeypatch, payload, status)
    with pytest.raises(ValueError) as exc:
        await native.EventifyNode.load_field_options("eventid", credential())
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1
    if payload["message"] != TOKEN:
        assert payload["message"] in str(exc.value)


@pytest.mark.asyncio
async def test_token_and_password_are_redacted_from_provider_data(monkeypatch):
    transport(monkeypatch, {"resource": [{"firstname": TOKEN, "session_token": TOKEN, "userpassword": "private-password"}]})
    result = await node({"operation": "list_attendees", "eventid": 42}).execute({})
    assert TOKEN not in str(result) and "private-password" not in str(result)
    assert result["data"]["resource"] == [{"firstname": "[redacted]"}]


@pytest.mark.parametrize("config", [
    {"operation": "update_attendee", "userid": 7},
    {"operation": "update_attendee", "userid": 7, "form_number": 123456},
    {"operation": "update_attendee", "userid": 7, "form_number": 123456, "details_form": "{}"},
    {"operation": "update_speaker", "speakerid": 7, "eventid": 42},
    {"operation": "get_session", "sessionid": -1},
    {"operation": "search_attendee", "eventid": 42, "searchtype": "arbitrary", "searchvalue": "x"},
])
def test_bad_inputs_fail_before_request(config):
    with pytest.raises(ValueError):
        native.EventifyNode.parse_config({"config": config})


def test_pasted_credential_has_a_default_type_and_human_fields():
    parsed = native.EventifySessionTokenCredential(session_token="  " + TOKEN + "  ")
    assert parsed.credential_type == "eventify_session_token"
    assert parsed.session_token == TOKEN
    for bad in ["https://example.com/token", "<token>", "Bearer token"]:
        with pytest.raises(ValidationError):
            native.EventifySessionTokenCredential(session_token=bad)


def test_provider_fixture_records_pin_and_nullability_contradiction():
    fixture = json.loads((Path(__file__).parent / "fixtures/eventify/contract-excerpts.json").read_text())
    assert fixture["version"] == "4.0.1"
    schema = fixture["schemas"]["CreateAppUserRequestBodySchema"]
    assert schema["properties"]["speakeridfk"] == {"type": "integer", "example": None}
    assert "speakeridfk" in schema["required"]
