"""Native factory regressions using the provider's published response examples."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import timerex_node as native
from nodes.core.registry import NodeFactory

KEY = "SyntheticTimeRexKey12345678901234567890123456789012345678901234567"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/timerex/responses.json").read_text())
EXPECTED = {
    "get_primary_team": ("GET", "/user/me/teams/primary", 200),
    "list_teams": ("GET", "/user/me/teams", 200),
    "get_team": ("GET", "/teams/{team_id}", 200),
    "list_calendars": ("GET", "/teams/{team_id}/calendars", 200),
    "get_calendar": ("GET", "/calendars/{calendar_id}", 200),
    "list_events": ("GET", "/calendars/{calendar_id}/events", 200),
    "get_event": ("GET", "/events/{event_id}", 200),
    "cancel_event": ("POST", "/events/{event_id}/cancel", 200),
    "get_one_time_url": ("GET", "/calendars/one-time-url/{one_time_url_id}", 200),
    "create_one_time_url": ("POST", "/calendars/{calendar_id}/one-time-url", 201),
    "watch_one_time_url": ("POST", "/calendars/one-time-url/{one_time_url_id}/watch", 201),
}
CONFIGS = {
    "get_primary_team": {}, "list_teams": {"nextPageToken": "next-page +/&?"},
    "get_team": {"team_id": "ac75a81610af3315da22"},
    "list_calendars": {"team_id": "primary", "sort_order": "desc"},
    "get_calendar": {"calendar_id": "3779dc6c86e3157f93e2"},
    "list_events": {"calendar_id": "3779dc6c86e3157f93e2", "startTime": "2023-12-19 15:00:00", "endTime": "2023-12-19 16:00:00"},
    "get_event": {"event_id": "b7af5ef04e4b8451e0a9"},
    "cancel_event": {"event_id": "b7af5ef04e4b8451e0a9", "cancellation_reason": "Event cancelled"},
    "get_one_time_url": {"one_time_url_id": "3430d457288bc8f8f819"},
    "create_one_time_url": {"calendar_id": "3779dc6c86e3157f93e2"},
    "watch_one_time_url": {"one_time_url_id": "3430d457288bc8f8f819", "token": "xhjisop335", "notification_url": "https://third-party-app.com/timerex/watch"},
}


def node(operation, **config):
    return NodeFactory.create_node(node_type="automation-timerex", node_id="test-timerex",
        node_data={"config": {"operation": operation, **config},
            "credentials": {"credential_type": "timerex_api_key", "api_key": KEY}})


def mock(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_all_documented_operations_use_one_fixed_request(monkeypatch, operation):
    method, template, code = EXPECTED[operation]
    fixture = FIXTURES.get(method + " " + template)
    requests = mock(monkeypatch, lambda _: httpx.Response(code, json=fixture["body"]) if fixture else httpx.Response(code))
    result = await node(operation, **CONFIGS[operation]).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "timerex.net"
    assert request.url.path == "/api/beta" + template.format(**CONFIGS[operation])
    assert request.headers["x-api-key"] == KEY and "Authorization" not in request.headers
    expected = {k: v for k, v in CONFIGS[operation].items() if k in ("nextPageToken", "sort_order", "startTime", "endTime")}
    assert dict(request.url.params) == expected
    if operation == "cancel_event":
        assert json.loads(request.content) == {"cancellation_reason": "Event cancelled"}
    elif operation == "watch_one_time_url":
        assert json.loads(request.content) == {"token": "xhjisop335", "notification_url": "https://third-party-app.com/timerex/watch"}
    elif method == "POST":
        assert request.content == b""
    if operation.startswith("list_"):
        assert result["has_more"] == bool(fixture["body"].get("nextPageToken"))


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 429, 500])
async def test_provider_errors_and_redirects_never_retry_or_leak_key(monkeypatch, code):
    requests = mock(monkeypatch, lambda _: httpx.Response(code, json={"message": "Rejected " + KEY}, headers={"Location": "https://other.test"}))
    result = await node("create_one_time_url", calendar_id="calendar").execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert KEY not in str(result) and len(requests) == 1
    assert result["write_outcome_unknown"] == (code >= 500)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"items": "bad"}, {"items": [None]}, {"items": [], "nextPageToken": "same"}, {"message": "error"}])
async def test_malformed_page_or_stalled_cursor_fails(monkeypatch, body):
    mock(monkeypatch, lambda _: httpx.Response(200, json=body))
    assert (await node("list_teams", nextPageToken="same").execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_cancel_accepts_documented_bodyless_200_and_omitted_reason(monkeypatch):
    requests = mock(monkeypatch, lambda _: httpx.Response(200))
    assert (await node("cancel_event", event_id="event").execute({}))["cancelled"]
    assert json.loads(requests[0].content) == {}


@pytest.mark.parametrize("operation, config", [
    ("get_team", {"team_id": "../other"}), ("get_calendar", {"calendar_id": "https://other.test"}),
    ("list_events", {"calendar_id": "id", "startTime": "2026-02-30 10:00:00"}),
    ("list_events", {"calendar_id": "id", "startTime": "2026-01-02 10:00:00", "endTime": "2026-01-01 10:00:00"}),
    ("watch_one_time_url", {"one_time_url_id": "id", "token": "a", "notification_url": "http://example.com"}),
    ("get_user", {}), ("get_primary_team", {"extra": "bad"}),
])
def test_bad_inputs_rejected_before_request(operation, config):
    with pytest.raises(ValueError):
        node(operation, **config)


def test_manual_credential_default_and_secret_shape():
    assert native.TimeRexAPIKeyCredential(api_key=KEY).credential_type == "timerex_api_key"
    with pytest.raises(ValidationError):
        native.TimeRexAPIKeyCredential(api_key="https://example.com/key")


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_connect_shows_issuing_team_or_identity_fallback(monkeypatch, empty):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence

    def respond(request):
        path = request.url.path.removeprefix("/api/beta")
        if path == "/user/me/teams":
            body = {"items": []} if empty else FIXTURES["GET /user/me/teams"]["body"]
        else:
            assert path == "/user/me/teams/primary"
            body = FIXTURES["GET /user/me/teams/primary"]["body"]
        return httpx.Response(200, json=body)
    requests = mock(monkeypatch, respond)

    async def run_operation(**kwargs):
        return await node(kwargs["operation"], **kwargs["arguments"]).execute({})
    monkeypatch.setattr(run_op, "run_node_operation", run_operation)
    result = await collect_evidence(node_type="automation-timerex", user_id="test-user",
        credential_data={"credential_type": "timerex_api_key", "api_key": KEY})
    assert result.reachable is True
    if empty:
        assert result.account_label == "My space" and len(requests) == 2
    else:
        assert result.samples[0].label == "My space" and len(requests) == 1
