"""Prepared actual native seam regressions, not executed provider proof.

Synthetic credential resolution and HTTP transport isolate contract behavior;
live SQL access and real installation permissions remain separate gates.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
import json
import httpx
import pytest
from nodes import churchtools_node as native
from nodes.core.credential_connect import validate_for_connect
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation

TYPE = "automation-churchtools"
USER = "00000000-0000-4000-8000-000000000001"
CID = "00000000-0000-4000-8000-000000000042"
GUID = "11111111-1111-4111-8111-111111111111"
CREDENTIAL = {"credential_type": "churchtools", "instance_url": "https://fixture.church.tools", "login_token": "synthetic-token-private", "expected_person_id": "7"}
PERSON = {"id": 7, "guid": GUID, "firstName": "Fixture", "lastName": "Person", "email": "omit@example.test", "birthday": "2000-01-01", "customPrivate": "omit-private"}
IDENTITY = {"data": PERSON}
CALENDAR = {"id": 2, "name": "Fixture Calendar", "type": "personal", "sortKey": 10, "color": "#aabbcc", "campusId": None, "eventTemplateId": None, "iCalSourceUrl": None, "evTermineEventTypeId": None, "syncToEvTermine": False, "randomUrl": "omit-subscription-secret"}
CATEGORY = {"id": 3, "name": "Fixture Wiki", "sortKey": 10, "inMenu": False, "fileAccessWithoutPermission": False, "campusId": None, "permissions": {"canEdit": True}}
PAGE = {"guid": GUID, "title": "Fixture Page", "version": 1, "wikiCategory": {"id": 3}, "text": "omit-content", "permissions": {"canEdit": True, "canDelete": True}}


def node(operation, credential=CREDENTIAL, **args):
    return NodeFactory.create_node(node_id="churchtools-fixture", node_type=TYPE, node_data={"config": {"operation": operation, **args}, "credentials": credential}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        calls.append(request)
        value = responses.pop(0)
        if callable(value):
            value = value()
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as value:
            yield value
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("limit", [True, "10", "10x", 1.5, 0, 101])
def test_actual_factory_strict_page_bound_before_io(limit, transport):
    with pytest.raises(ValueError):
        node("list_persons", limit=limit)
    assert transport[0] == []


@pytest.mark.parametrize("origin", ["http://fixture.church.tools", "https://127.0.0.1", "https://localhost", "https://tenant.local", "https://public.example:0", "https://public.example/api", "https://user@public.example", "https://public.example?token=x"])
def test_tenant_url_admission_before_transport(origin, transport):
    with pytest.raises(ValueError):
        node("check_connection", credential={**CREDENTIAL, "instance_url": origin})
    assert transport[0] == []


def test_original_foreign_row_tag_precedes_reconciliation(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=TYPE, node_data={"config": {"operation": "check_connection"}, "credentials": {**CREDENTIAL, "credential_type": "foreign"}, "credentialIds": {"churchtools": CID}}, sio=None, sid=None)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_visible_only_connect_uses_authenticated_whoami_and_login_header(transport):
    transport[1].append(IDENTITY)
    verdict = await validate_for_connect(credential_type="churchtools", credential_data={key: value for key, value in CREDENTIAL.items() if key != "credential_type"}, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == "churchtools"
    assert transport[0][0].url.path == "/api/whoami"
    assert transport[0][0].url.params["only_allow_authenticated"] == "true"
    assert transport[0][0].headers["Authorization"] == "Login synthetic-token-private"


@pytest.mark.asyncio
@pytest.mark.parametrize("person_id", [0, -1, True, 8])
async def test_anonymous_or_wrong_person_http200_is_not_identity(transport, person_id):
    transport[1].append({"data": {**PERSON, "id": person_id}})
    with pytest.raises(ValueError):
        await node("check_connection").execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_actual_people_page_projection_and_integer_query(transport):
    transport[1].extend([IDENTITY, {"data": [PERSON], "meta": {"pagination": {"current": 1, "lastPage": 2}}}])
    result = await node("list_persons", limit=10).execute({})
    assert result["data"]["next_page"] == 2
    assert transport[0][-1].url.params["limit"] == "10"
    assert all(value not in repr(result) for value in ("omit-private", "omit@example.test", "2000-01-01"))


@pytest.mark.asyncio
async def test_calendar_put_preserves_complete_settings_and_refuses_feed_import(transport):
    transport[1].extend([IDENTITY, {"data": CALENDAR}, {"data": {**CALENDAR, "name": "Renamed"}}])
    result = await node("update_calendar", calendar_id="2", name="Renamed").execute({})
    body = json.loads(transport[0][-1].content)
    assert body == {key: CALENDAR[key] for key in ("sortKey", "color", "campusId", "eventTemplateId", "iCalSourceUrl", "evTermineEventTypeId", "syncToEvTermine")} | {"name": "Renamed"}
    assert result["data"]["readback_verified"] is False and "randomUrl" not in repr(result)
    transport[1].extend([IDENTITY, {"data": {**CALENDAR, "iCalSourceUrl": "https://feed.example/secret"}}])
    with pytest.raises(ValueError, match="local calendar"):
        await node("update_calendar", calendar_id="2", name="Refused").execute({})
    assert all(request.method == "GET" for request in transport[0][-2:])


@pytest.mark.asyncio
async def test_wiki_exact_parent_guid_text_version_write_and_204_delete(transport):
    transport[1].extend([IDENTITY, {"data": [CATEGORY]}, {"data": PAGE}, {"data": {**PAGE, "version": 2}}])
    result = await node("update_wiki_page", wiki_category_id="3", page_guid=GUID, text="New text").execute({})
    assert json.loads(transport[0][-1].content) == {"text": "New text"}
    assert result["data"]["version"] == 2 and "omit-content" not in repr(result)
    transport[1].extend([IDENTITY, {"data": [CATEGORY]}, {"data": PAGE}, httpx.Response(204)])
    result = await node("delete_wiki_page", wiki_category_id="3", page_guid=GUID).execute({})
    assert result["data"]["delete_acknowledged"] and not result["data"]["readback_verified"]


@pytest.mark.asyncio
async def test_cross_calendar_child_is_rejected(transport):
    transport[1].extend([IDENTITY, {"data": CALENDAR}, {"data": {"appointment": {"id": 4, "calendar": {"id": 99}, "title": "Wrong parent"}}}])
    with pytest.raises(ValueError, match="outside"):
        await node("get_appointment", calendar_id="2", appointment_id="4").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_safe_tri_state_provider_errors(transport, status):
    transport[1].append(httpx.Response(status, text="synthetic-token-private confidential body"))
    result = await native.ChurchToolsNode.validate_credential_access(CREDENTIAL)
    error = result["error"]
    assert result["valid"] is (False if status == 401 else None)
    assert "synthetic-token-private" not in error and "confidential" not in error


@pytest.fixture
def current_row(monkeypatch):
    state = {"credential": dict(CREDENTIAL)}
    monkeypatch.setattr(native, "resolve_credential_with_owner_fallback", AsyncMock(side_effect=lambda *args, **kwargs: state["credential"]))
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["token", "type", "person", "revoked"])
async def test_actual_saved_dispatch_discards_inflight_credential_changes(transport, current_row, change):
    def returned():
        current_row["credential"] = None if change == "revoked" else {**CREDENTIAL, **{
            "token": {"login_token": "rotated-token"},
            "type": {"credential_type": "foreign"},
            "person": {"expected_person_id": "8"},
        }[change]}
        return IDENTITY
    transport[1].append(returned)
    with pytest.raises(ValueError, match="unavailable"):
        await run_node_operation(node_type=TYPE, operation="check_connection", arguments={}, credential_data=CREDENTIAL, user_id=USER, credential_id=CID, pool=object(), organization_id=None)
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_saved_missing_caller_refuses_before_provider(transport):
    value = node("check_connection")
    value.user_id = None
    value.node_data["credential_id"] = CID
    with pytest.raises(ValueError, match="unavailable"):
        await value.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [None, {**CREDENTIAL, "login_token": "rotated-token"}])
async def test_picker_rechecks_bound_saved_credential_before_provider(transport, current_row, changed):
    authority = await native._Authority.create(CREDENTIAL, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    current_row["credential"] = changed
    with pytest.raises(ValueError, match="unavailable"):
        await native.ChurchToolsNode.load_field_options("page_guid", {**CREDENTIAL, native._AUTH_KEY: authority}, context={"wiki_category_id": "3"})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_person_create_is_200_with_exact_department_and_hidden_metadata(transport):
    catalogs = {name: [{"id": 1, "name": "Fixture"}] for name in ("departments", "statuses", "campuses", "groupTypes", "groupStatuses", "groupCategories")}
    transport[1].extend([IDENTITY, {"data": catalogs}, {"data": {**PERSON, "id": 9}}])
    result = await node("create_person", department_id="1", first_name="Synthetic", last_name="Owned Fixture").execute({})
    assert json.loads(transport[0][-1].content) == {"firstName": "Synthetic", "lastName": "Owned Fixture", "departmentIds": [1], "visibility": "hidden"}
    assert result["data"]["id"] == 9 and result["data"]["write_acknowledged"]


@pytest.mark.asyncio
async def test_missing_wiki_parent_and_bad_collection_fail_without_scan(transport):
    with pytest.raises(ValueError):
        await native.ChurchToolsNode.load_field_options("page_guid", CREDENTIAL, context={})
    assert transport[0] == []
    transport[1].extend([IDENTITY, {"data": [PERSON], "meta": {"pagination": {"current": True, "lastPage": 1}}}])
    with pytest.raises(ValueError):
        await node("list_persons").execute({})
    assert len(transport[0]) == 2


@pytest.mark.asyncio
async def test_authenticated_identity_does_not_invent_permission_level_range(transport):
    transport[1].append({"data": {**PERSON, "securityLevelForPerson": -1, "editSecurityLevelForPerson": -1}})
    result = await node("check_connection").execute({})
    assert result["data"] == {"person_id": 7, "guid": GUID}
    assert len(transport[0]) == 1


# Isolated parser fixtures follow the occurrence shape in the pinned OpenAPI;
# they are not provider-authored responses or live conformance proof.
@pytest.mark.asyncio
async def test_appointment_occurrences_keep_calculated_dates_and_repeated_series(transport):
    base = {"id": 4, "calendar": CALENDAR, "title": CALENDAR["name"],
            "startDate": "2026-09-20T08:00:00Z", "endDate": "2026-09-20T09:30:00Z"}
    first = {"startDate": "2026-09-20T08:00:00Z", "endDate": "2026-09-20T09:30:00Z"}
    second = {"startDate": "2026-09-27T08:00:00Z", "endDate": "2026-09-27T09:30:00Z"}
    occurrences = [{"appointment": {"base": base, "calculated": dates}} for dates in (first, second)]
    transport[1].extend([IDENTITY, {"data": CALENDAR}, {"data": occurrences}])
    result = await node("list_appointments", calendar_id="2", from_date="2026-09-01", to_date="2026-09-30").execute({})
    assert [row["id"] for row in result["data"]["items"]] == [4, 4]
    assert [{key: row[key] for key in ("startDate", "endDate")} for row in result["data"]["items"]] == [first, second]
    assert all(row["calendar_id"] == 2 for row in result["data"]["items"])
    transport[1].extend([IDENTITY, {"data": CALENDAR}, {"data": [occurrences[0], occurrences[0]]}])
    with pytest.raises(ValueError):
        await node("list_appointments", calendar_id="2", from_date="2026-09-01", to_date="2026-09-30").execute({})


@pytest.mark.parametrize("to_date,valid", [("2026-09-01", True), ("2026-10-01", True), ("2026-10-02", False), ("2026-08-31", False)])
def test_appointment_range_counts_inclusive_calendar_dates(to_date, valid):
    if valid:
        node("list_appointments", calendar_id="2", from_date="2026-09-01", to_date=to_date)
    else:
        with pytest.raises(ValueError):
            node("list_appointments", calendar_id="2", from_date="2026-09-01", to_date=to_date)


@pytest.mark.asyncio
async def test_private_host_override_refused_before_transport(monkeypatch, transport):
    monkeypatch.setattr(native, "allow_private_hosts", lambda: True)
    with pytest.raises(ValueError, match="public-host enforcement"):
        await node("check_connection").execute({})
    assert transport[0] == []


def test_config_validation_reports_foreign_credential_without_raising():
    result = native.ChurchToolsNode.validate_config({"credentials": {**CREDENTIAL, "credential_type": "foreign"}, "config": {"operation": "check_connection"}})
    assert result["valid"] is False
    assert result["errors"] == ["A ChurchTools Login-token credential is required"]
