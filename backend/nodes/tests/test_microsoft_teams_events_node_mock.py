"""Local wire and published-response regressions; no live Microsoft account."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes.microsoft_teams_events_node import MODELS, MicrosoftTeamsEventsNode, TeamsEventsNodeConfig, TeamsEventsOAuthCredential

VALUES = dict(webinar_id="webinar@tenant", presenter_id="presenter", registration_id="registrant", session_id="session", question_id="question", user_id="user", tenant_id="tenant", display_name="Quarterly briefing", description="Product news", start_time="2026-12-01T10:00:00", end_time="2026-12-01T11:00:00", time_zone="Pacific Standard Time", audience="organization", bio="Product manager", company="Contoso", job_title="Manager", answer_input_type="multiChoice", answer_choices=["Sales", "Engineering"], is_required=True)
BASE = "/solutions/virtualEvents/webinars"
# Expected wire routes are independent of the implementation catalog.
ROUTES = {
    "get_account": ("GET", "/me"),
    "list_my_webinars": ("GET", BASE + "/getByUserRole(role='organizer')"),
    "get_webinar": ("GET", BASE + "/webinar@tenant"),
    "create_webinar": ("POST", BASE),
    "update_webinar": ("PATCH", BASE + "/webinar@tenant"),
    "create_presenter": ("POST", BASE + "/webinar@tenant/presenters"),
    "update_presenter": ("PATCH", BASE + "/webinar@tenant/presenters/presenter"),
    "get_registration_configuration": ("GET", BASE + "/webinar@tenant/registrationConfiguration"),
    "list_registration_questions": ("GET", BASE + "/webinar@tenant/registrationConfiguration/questions"),
    "create_registration_question": ("POST", BASE + "/webinar@tenant/registrationConfiguration/questions"),
    "delete_registration_question": ("DELETE", BASE + "/webinar@tenant/registrationConfiguration/questions/question"),
    "get_registration": ("GET", BASE + "/webinar@tenant/registrations/registrant"),
    "list_sessions": ("GET", BASE + "/webinar@tenant/sessions"),
    "get_session": ("GET", BASE + "/webinar@tenant/sessions/session"),
}
LISTS = {"list_my_webinars", "list_registration_questions", "list_sessions"}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/microsoft-teams-events/documented_responses.json").read_text())


def node(operation, **overrides):
    cls = MODELS[operation]
    values = {k: v for k, v in VALUES.items() if k in cls.model_fields}
    values.update(overrides)
    return MicrosoftTeamsEventsNode(node_id="teams-test", node_type="automation-microsoft-teams-events", node_data={}, config=TeamsEventsNodeConfig(config=cls(**values), credentials=TeamsEventsOAuthCredential(access_token="test-access", refresh_token="test-refresh", expires_at="2099-01-01T00:00:00Z")), sio=None, sid=None, workflow_id="workflow-test")


@pytest.fixture
def wire(monkeypatch):
    from nodes.core import oauth_refresh
    from nodes import microsoft_teams_events_node as module
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", AsyncMock(return_value="test-access"))
    real = httpx.AsyncClient
    def install(respond):
        monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(respond)))
    return install


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ROUTES)
async def test_documented_routes_and_payloads(wire, operation):
    seen = []
    def respond(request):
        seen.append(request)
        if request.method == "DELETE" or operation == "update_webinar":
            return httpx.Response(204)
        return httpx.Response(200, json={"value": [{"id": "example"}]} if operation in LISTS else {"id": "example"})
    wire(respond)
    result = await node(operation).execute({})
    assert len(seen) == 1
    request = seen[0]
    method, path = ROUTES[operation]
    assert (request.method, request.url.host, request.url.path) == (method, "graph.microsoft.com", "/v1.0" + path)
    assert request.headers["Authorization"] == "Bearer test-access"
    assert result["status"] == "success"
    if method in ("GET", "DELETE"):
        assert not request.content
    else:
        body = json.loads(request.content)
        assert body["@odata.type"].startswith("#microsoft.graph.")
        assert not set(body) & {"id", "status", "createdBy", "registrationWebUrl"}
        if operation == "create_webinar":
            assert body["startDateTime"]["dateTime"] == VALUES["start_time"]
            assert body["endDateTime"]["timeZone"] == "Pacific Standard Time"
            assert body["description"]["contentType"] == "text"
        if operation == "update_webinar":
            assert set(body) == {"@odata.type", "displayName", "description"}
        if operation == "create_presenter":
            assert body["identity"] == {"@odata.type": "#microsoft.graph.communicationsUserIdentity", "id": "user", "tenantId": "tenant"}
        if operation == "update_presenter":
            assert body["presenterDetails"]["bio"]["content"] == "Product manager"
        if operation == "create_registration_question":
            assert body["answerChoices"] == ["Sales", "Engineering"] and body["isRequired"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_published_response_examples(wire, operation):
    fixture = FIXTURES[operation]
    wire(lambda request: httpx.Response(fixture["status"], json=fixture["body"]))
    out = await node(operation).execute({})
    assert out["items"] == fixture["body"]["value"] if operation in LISTS else out["data"] == fixture["body"]


@pytest.mark.asyncio
async def test_next_page_preserves_graph_cursor(wire):
    link = "https://graph.microsoft.com/v1.0" + BASE + "/webinar%40tenant/sessions?$skiptoken=opaque"
    seen = []
    wire(lambda request: (seen.append(request) or httpx.Response(200, json={"value": [], "@odata.nextLink": link})))
    assert (await node("list_sessions").execute({}))["next_link"] == link
    await node("list_sessions", next_link=link).execute({})
    assert seen[1].url.params["$skiptoken"] == "opaque"


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["https://evil.example/v1.0/me", "https://graph.microsoft.com/v1.0/me/messages", "https://graph.microsoft.com/v1.0/solutions/virtualEvents/webinars/other/sessions", "https://graph.microsoft.com:443/v1.0/solutions/virtualEvents/webinars/webinar%40tenant/sessions"])
async def test_continuation_cannot_redirect_bearer(wire, link):
    wire(lambda request: pytest.fail("Unsafe continuation reached transport"))
    with pytest.raises(ValueError, match="Next page link"):
        await node("list_sessions", next_link=link).execute({})


@pytest.mark.asyncio
async def test_provider_error_redacts_secrets(wire):
    wire(lambda request: httpx.Response(403, json={"error": {"message": "Forbidden test-access test-refresh"}}))
    with pytest.raises(ValueError) as exc:
        await node("get_account").execute({})
    assert "403" in str(exc.value) and "Forbidden" in str(exc.value)
    assert "test-access" not in str(exc.value) and "test-refresh" not in str(exc.value)


@pytest.mark.parametrize("operation,overrides", [("get_webinar", {"webinar_id": "../me"}), ("get_webinar", {"webinar_id": "id?query"}), ("create_webinar", {"end_time": "2026-11-01T10:00:00"}), ("create_webinar", {"start_time": "invalid"}), ("update_webinar", {"display_name": None, "description": None}), ("create_registration_question", {"answer_choices": []})])
def test_invalid_config(operation, overrides):
    with pytest.raises(ValidationError):
        node(operation, **overrides)


def test_credentials_and_scopes():
    assert TeamsEventsOAuthCredential(access_token="test-token").credential_type == "microsoft_teams_events_oauth"
    from nodes.scopes.microsoft_teams_events import TEAMS_EVENTS_SCOPES
    assert TEAMS_EVENTS_SCOPES.keys_declared == set(ROUTES)
    assert MicrosoftTeamsEventsNode.connection_evidence.operation == "list_my_webinars"
