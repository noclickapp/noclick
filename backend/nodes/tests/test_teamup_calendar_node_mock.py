"""Teamup contract routing and credential/response regressions; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import teamup_calendar_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

CONFIGS = json.loads((Path(__file__).parent / "fixtures/teamup-calendar/operations.json").read_text())
CONTRACT = json.loads((Path(__file__).parent / "fixtures/teamup-calendar/contract.json").read_text())["operations"]
CREDENTIAL = {"credential_type": "teamup_calendar_api_key", "api_key": "owned-api-secret", "calendar_key": "ks123456abc789def0"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="fixture", node_type="automation-teamup-calendar",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, status=200, body=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(CONFIGS))
async def test_teamup_calendar_exact_contract_routes_and_json(monkeypatch, operation):
    contract = CONTRACT[operation]
    method, route, status = contract["method"], contract["path"], contract["status"]
    cfg = CONFIGS[operation]
    body = {"events": [], "subcalendars": [], "event": {"id": "123456"}, "subcalendar": {"id": 123}, "configuration": {}, "data": {}, "undo_id": "undo"}
    if operation == "list_signups":
        body = [{"id": "654321", "name": "Mark Doe"}]
    requests = transport(monkeypatch, status, body)
    result = await node(cfg).execute({})
    assert result["status"] == "success"
    request = requests[0]
    assert len(requests) == 1 and request.method == method
    assert request.url.host == "api.teamup.com"
    path_values = {"calendarKeyOrId": CREDENTIAL["calendar_key"], "calendarKey": CREDENTIAL["calendar_key"],
        **{wire: cfg[key] for key, wire in {"event_id":"eventId", "comment_id":"commentId", "signup_id":"signupId", "subcalendar_id":"resourceId"}.items() if key in cfg}}
    assert request.url.path == route.format(**path_values)
    assert request.headers["Teamup-Token"] == CREDENTIAL["api_key"]
    assert "Authorization" not in request.headers
    if method in {"POST", "PUT", "PATCH"}:
        sent = json.loads(request.content)
        assert not ({"operation", "event_id", "comment_id", "subcalendar_id", "signup_id", "input_format"} & sent.keys())
        if operation in {"create_event", "update_event"}:
            assert sent["signup_enabled"] is False and sent["comments_enabled"] is False
            assert sent["attachments"] == ([] if operation == "create_event" else cfg["attachments"])
            assert sent["start_dt"].startswith("2026-11-09T10:00:00")
        if operation == "update_subcalendar":
            assert sent == {"name": "Peter's Schedule", "active": False}
    if operation == "list_events":
        assert dict(request.url.params) == {"startDate":"2026-11-09", "endDate":"2026-11-10", "tz":"Europe/Zurich", "format":"markdown"}
    if operation == "delete_event":
        assert dict(request.url.params) == {"version":"abcd", "redit":"single"}


@pytest.mark.asyncio
async def test_teamup_calendar_optional_bearer_and_evidence_redaction(monkeypatch):
    cred = {**CREDENTIAL, "bearer_token": "owned-bearer-secret"}
    requests = transport(monkeypatch, body={"subcalendars": [{"id": 123, "name": "Planning", "private": list(cred.values())}]})
    result = await node({"operation":"list_subcalendars", "limit":1}, cred).execute({})
    assert result["items"][0]["name"] == "Planning" and result["next_offset"] == 1
    assert requests[0].headers["Authorization"] == "Bearer owned-bearer-secret"
    for secret in (cred["api_key"], cred["calendar_key"], cred["bearer_token"]):
        assert secret not in str(result)
    assert native.TeamupCalendarNode.connection_evidence.operation == "list_subcalendars"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301,302,400,401,403,404,429,500])
async def test_teamup_calendar_provider_rejections_and_redirects(monkeypatch, status):
    requests = transport(monkeypatch, status, {"error": "Denied owned-api-secret"})
    result = await node({"operation":"list_subcalendars"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Denied" in result["error"] and "owned-api-secret" not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_teamup_calendar_error_envelope_and_malformed_list(monkeypatch):
    transport(monkeypatch, body={"error": "Denied"})
    assert (await node({"operation":"list_subcalendars"}).execute({}))["status"] == "error"
    transport(monkeypatch, body={"subcalendars": {}})
    with pytest.raises(ValueError, match="list response"):
        await node({"operation":"list_subcalendars"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation":"get_event", "event_id":"../events"},
    {"operation":"delete_subcalendar", "subcalendar_id":"1/keys"},
    {"operation":"list_events", "start_date":"2026-11-10", "end_date":"2026-11-09"},
    {**CONFIGS["create_event"], "signup_enabled":True},
    {**CONFIGS["create_event"], "comments_enabled":True},
    {**CONFIGS["update_event"], "attachments":[{"unexpected":"value"}]},
    {"operation":"list_subcalendars", "url":"https://example.com"},
])
def test_teamup_calendar_refuses_invalid_or_incomplete_input(config):
    with pytest.raises((ValueError,ValidationError)):
        native.TeamupCalendarFullConfig.model_validate({"config":config,"credentials":CREDENTIAL})


def test_teamup_calendar_manual_credential_defaults_and_shape():
    parsed = native.TeamupCalendarAPIKeyCredential.model_validate({"api_key":" actual-key ", "calendar_key":"ks123456"})
    assert parsed.credential_type == "teamup_calendar_api_key" and parsed.api_key == "actual-key"
    shaped, errors, _ = shape_credential("teamup_calendar_api_key", {"api_key":"actual-key", "calendar_key":"ks123456", "bearer_token":" "})
    assert errors == {} and shaped["bearer_token"] is None
    for key in ["https://teamup.com/ks123456", "ks123/evil", "key with spaces"]:
        with pytest.raises(ValueError):
            native.TeamupCalendarAPIKeyCredential.model_validate({**CREDENTIAL,"calendar_key":key})
