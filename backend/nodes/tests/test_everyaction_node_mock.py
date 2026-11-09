"""EveryAction native factory and wire-contract regressions, using synthetic keys."""
import base64
import json
import httpx
import pytest
from nodes import everyaction_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "everyaction_api_key", "application_name": "testApplication", "api_key": "synthetic-key-abcdef", "database_mode": "1"}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id="everyaction-test", node_type="automation-everyaction", node_data={"config": config, "credentials": CREDENTIAL})

def transport(monkeypatch, status=200, body=None):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls

@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", [
    ({"operation": "check_connection"}, "GET", "/apiKeyProfiles"),
    ({"operation": "get_person", "van_id": "100476252"}, "GET", "/people/100476252"),
    ({"operation": "find_person", "first_name": "James", "last_name": "Gordon"}, "POST", "/people/find"),
    ({"operation": "find_or_create_person", "first_name": "James", "last_name": "Gordon"}, "POST", "/people/findOrCreate"),
    ({"operation": "update_person", "van_id": "100476252", "last_name": "Gordon"}, "POST", "/people/100476252"),
    ({"operation": "list_notes", "van_id": "100476252"}, "GET", "/people/100476252/notes"),
    ({"operation": "create_note", "van_id": "100476252", "text": "Great chat!"}, "POST", "/people/100476252/notes"),
    ({"operation": "update_note", "van_id": "100476252", "note_id": "225", "text": "Great chat!"}, "PUT", "/people/100476252/notes/225"),
    ({"operation": "list_events"}, "GET", "/events"),
    ({"operation": "get_event", "event_id": 1370}, "GET", "/events/1370"),
    ({"operation": "list_signups", "event_id": 1370}, "GET", "/signups"),
    ({"operation": "get_signup", "event_signup_id": 2452}, "GET", "/signups/2452"),
    ({"operation": "delete_signup", "event_signup_id": 2452}, "DELETE", "/signups/2452"),
    ({"operation": "list_saved_lists"}, "GET", "/savedLists"),
    ({"operation": "get_saved_list", "saved_list_id": 123}, "GET", "/savedLists/123"),
    ({"operation": "list_activist_codes"}, "GET", "/activistCodes"),
    ({"operation": "get_person_activist_codes", "van_id": "100476252"}, "GET", "/people/100476252/activistCodes"),
    ({"operation": "apply_code", "van_id": "100476252", "code_id": "20545"}, "POST", "/people/100476252/codes"),
    ({"operation": "get_contribution", "contribution_id": 4482}, "GET", "/contributions/4482"),
])
async def test_native_routes_single_page_and_auth(monkeypatch, config, method, path):
    page = {"items": [{"name": "People for Good"}], "nextPageLink": "https://untrusted.example/page", "count": 1}
    calls = transport(monkeypatch, body=page)
    assert await node(config).execute({}) == {"status": "success", "http_status": 200, "data": page}
    assert len(calls) == 1
    assert (calls[0].method, str(calls[0].url).split('?')[0]) == (method, native.BASE + path)
    assert calls[0].headers["authorization"] == "Basic " + base64.b64encode(b"testApplication:synthetic-key-abcdef|1").decode()

@pytest.mark.asyncio
@pytest.mark.parametrize("update", [False, True])
async def test_signup_nested_references(monkeypatch, update):
    calls = transport(monkeypatch, status=204 if update else 201, body={"eventSignupId": 2452})
    config = {"operation": "update_signup" if update else "create_signup", "van_id": "100476252", "event_id": 1370,
              "event_shift_id": 2162, "role_id": 111687, "status_id": 4, "location_id": 272}
    if update: config["event_signup_id"] = 2452
    result = await node(config).execute({})
    expected = {"person": {"vanId": "100476252"}, "event": {"eventId": 1370}, "shift": {"eventShiftId": 2162},
                "role": {"roleId": 111687}, "status": {"statusId": 4}, "location": {"locationId": 272}}
    if update: expected["eventSignupId"] = 2452
    assert json.loads(calls[0].content) == expected
    assert (calls[0].method, calls[0].url.path) == (("PUT", "/v4/signups/2452") if update else ("POST", "/v4/signups"))
    assert len(calls) == 1 and result["status"] == "success"
    assert result["data"] == (None if update else {"eventSignupId": 2452})

@pytest.mark.asyncio
async def test_dates_note_privacy_and_query_filters(monkeypatch):
    calls = transport(monkeypatch, status=204)
    await node({"operation": "update_person", "van_id": "100476252", "date_of_birth": "1970-02-11", "first_name": "James"}).execute({})
    assert json.loads(calls[0].content) == {"dateOfBirth": "1970-02-11", "firstName": "James"}
    calls = transport(monkeypatch, status=204)
    await node({"operation": "create_note", "van_id": "100476252", "text": "Great chat!", "is_view_restricted": True, "note_category_id": 99}).execute({})
    assert json.loads(calls[0].content) == {"text": "Great chat!", "isViewRestricted": True, "category": {"noteCategoryId": 99}}
    calls = transport(monkeypatch, body={"items": []})
    await node({"operation": "list_events", "starting_after": "2019-06-23", "starting_before": "2019-06-26", "event_type_ids": "20036,81987", "top": 10}).execute({})
    assert dict(calls[0].url.params) == {"startingAfter": "2019-06-23", "startingBefore": "2019-06-26", "eventTypeIds": "20036,81987", "$top": "10"}

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
async def test_provider_errors_preserved_and_key_redacted(monkeypatch, status):
    calls = transport(monkeypatch, status=status, body={"errors": [{"text": "Rejected synthetic-key-abcdef"}]})
    result = await node({"operation": "check_connection"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status and result["status_code"] == status
    assert "Rejected [redacted]" in str(result) and CREDENTIAL["api_key"] not in str(result)
    assert len(calls) == 1

@pytest.mark.parametrize("config", [
    {"operation": "get_person", "van_id": "../notes"},
    {"operation": "update_person", "van_id": "100476252"},
    {"operation": "list_signups"},
    {"operation": "create_signup", "van_id": "100476252", "event_id": 1370},
    {"operation": "list_events", "top": 0},
    {"operation": "find_person", "first_name": "James", "last_name": "Gordon", "date_of_birth": "invalid"},
])
def test_required_inputs_and_path_safety(config):
    with pytest.raises(ValueError): node(config)

def test_manual_credential_default_and_reject_header_or_mode_suffix():
    assert native.EveryActionAPIKeyCredential(application_name="testApplication", api_key="synthetic-key-abcdef").credential_type == "everyaction_api_key"
    for key in ("synthetic-key-abcdef|1", "Basic header", "https://example.com/key"):
        with pytest.raises(ValueError): native.EveryActionAPIKeyCredential(application_name="testApplication", api_key=key)
