"""Unrun native Sling transport, parent, paging and privacy regression source."""
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import sling_node as node
from utils import ssrf

CREDENTIAL = {"credential_type": node.TYPES[0], "token": "fixture-token", "organization_id": "12"}
ORG = {"name": "Fixture Organization", "businessCategory": "Other", "password": "PRIVATE PASSWORD"}
GROUP = {"id": 21, "name": "Fixture Location", "type": "location", "timezone": "UTC", "phone": "PRIVATE PHONE", "budget": 1234}
USER = {"id": 31, "name": "Fixture User", "active": True, "email": "PRIVATE EMAIL", "password": "PRIVATE PASSWORD"}


@pytest.fixture
def transport(monkeypatch):
    calls = []
    state = {"status": 200, "payload": None, "calendar": [{"id": 41, "dtstart": "2026-10-07T08:00:00Z", "dtend": "2026-10-07T16:00:00Z", "summary": "PRIVATE SUMMARY", "wages": 999}], "groups": [GROUP], "users": [USER]}
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    async def remote(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.getsling.com"
        assert request.headers["Authorization"] == CREDENTIAL["token"]
        assert CREDENTIAL["token"] not in str(request.url)
        payload = deepcopy(state["payload"]) if state["payload"] is not None else {
            "/v1/organisations/12": ORG, "/v1/groups": state["groups"], "/v1/groups/21": GROUP,
            "/v1/groups/21/users": state["users"], "/v1/users": state["users"], "/v1/users/31": USER,
            "/v1/calendar/12/users/31": state["calendar"],
        }[request.url.path]
        return httpx.Response(state["status"], json=payload, headers={"Retry-After": "10"})
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(remote), **kwargs))
    return calls, state


@pytest.mark.parametrize("config", [node.GetOrganization(), node.ListGroups(), node.GetGroup(group_id="21"), node.ListUsers(), node.GetUser(user_id="31"), node.ListGroupUsers(group_id="21"), node.ListCalendarEvents(user_id="31", start="2026-10-07T00:00:00Z", end="2026-10-08T00:00:00Z")])
async def test_native_read_routes_project_private_fields(transport, config):
    calls, _ = transport
    result = await node.request_operation(CREDENTIAL, config)
    serialized = str(result)
    assert calls[0].url.path == "/v1/organisations/12"
    assert all(value not in serialized for value in ("PRIVATE EMAIL", "PRIVATE PHONE", "PRIVATE PASSWORD", "PRIVATE SUMMARY", "wages", "budget", CREDENTIAL["token"]))
    assert "data" in result and all(request.method == "GET" for request in calls)


async def test_execute_with_preparsed_config_and_empty_raw_data(transport):
    calls, _ = transport
    instance = node.SlingNode(
        node_id="fixture", node_type="automation-sling", node_data={},
        config=node.SlingNodeConfig.model_validate({
            "config": {"operation": "get_organization"}, "credentials": CREDENTIAL,
        }),
    )
    result = await instance.execute({})
    assert result["status"] == "success"
    assert result["data"]["requested_organization_id"] == "12"
    assert result["data"]["name"] == ORG["name"]
    assert len(calls) == 1 and calls[0].url.path == "/v1/organisations/12"


async def test_execute_still_validates_supplied_raw_data(transport):
    calls, _ = transport
    instance = node.SlingNode(
        node_id="fixture", node_type="automation-sling",
        node_data={"config": {"operation": "get_organization", "url": "https://example.test"}, "credentials": CREDENTIAL},
        config=node.SlingNodeConfig.model_validate({
            "config": {"operation": "get_organization"}, "credentials": CREDENTIAL,
        }),
    )
    with pytest.raises(ValueError, match="without request"):
        await instance.execute({})
    assert calls == []


async def test_group_type_uses_only_documented_filter(transport):
    calls, _ = transport
    result = await node.request_operation(CREDENTIAL, node.ListGroups(group_type="location"))
    assert dict(calls[-1].url.params) == {"type": "location"}
    assert result["data"]["scope"] == "token_current_organization"


@pytest.mark.parametrize("config", [node.GetGroup(group_id="22"), node.ListGroupUsers(group_id="22"), node.GetUser(user_id="32"), node.ListCalendarEvents(user_id="32", start="2026-10-07T00:00:00Z", end="2026-10-08T00:00:00Z")])
async def test_foreign_parent_stops_before_child_read(transport, config):
    calls, _ = transport
    with pytest.raises(ValueError, match="absent"):
        await node.request_operation(CREDENTIAL, config)
    assert len(calls) == 2 and calls[-1].url.path in {"/v1/groups", "/v1/users"}


async def test_calendar_offset_and_bound_continuation(transport):
    calls, _ = transport
    config = node.ListCalendarEvents(user_id="31", start="2026-10-07T00:00:00Z", end="2026-10-08T00:00:00Z", page_size=1)
    first = (await node.request_operation(CREDENTIAL, config))["data"]
    assert first["has_more"] is None and first["next_page_token"]
    assert dict(calls[-1].url.params) == {"dates": config.start + "/" + config.end, "pageSize": "1", "page": "0", "skipUnscheduled": "true", "showPlanningEvents": "false"}
    second = node.ListCalendarEvents.model_validate({**config.model_dump(), "page_token": first["next_page_token"]})
    await node.request_operation(CREDENTIAL, second)
    assert calls[-1].url.params["page"] == "1"
    changed = node.ListCalendarEvents.model_validate({**second.model_dump(), "page_size": 2})
    before = len(calls)
    with pytest.raises(ValueError, match="Continuation changed"):
        await node.request_operation(CREDENTIAL, changed)
    assert not any("calendar" in request.url.path for request in calls[before:])


@pytest.mark.parametrize("start,end", [("2026-10-07T00:00:00", "2026-10-08T00:00:00Z"), ("2026-10-07T00:00:00Z", "2026-10-07T00:00:00Z"), ("2026-10-07T00:00:00Z", "2026-12-07T00:00:00Z"), ("2026-02-30T00:00:00Z", "2026-03-01T00:00:00Z")])
def test_calendar_dates_are_valid_bounded_and_timezone_aware(start, end):
    with pytest.raises(ValueError):
        node.ListCalendarEvents(user_id="31", start=start, end=end)


@pytest.mark.parametrize("status", [202, 204, 301, 400, 401, 402, 403, 404, 405, 428, 429, 500])
async def test_non_200_never_success_or_leaks_provider_error(transport, status):
    calls, state = transport
    state.update(status=status, payload={"error": CREDENTIAL["token"]})
    with pytest.raises(node.SlingAPIError) as caught:
        await node.request_operation(CREDENTIAL, node.GetOrganization())
    assert caught.value.http_status == status and caught.value.retry_after == 10
    assert CREDENTIAL["token"] not in str(caught.value) and len(calls) == 1


@pytest.mark.parametrize("raw", [b'{"name":"x","name":"y"}', b'{"name":NaN}', b'{"value":1e999}', b'<html>not JSON</html>'])
def test_duplicate_nonfinite_and_non_json_refused(raw):
    with pytest.raises(ValueError, match="JSON"):
        node.finite_json(raw)


@pytest.mark.parametrize("rows", [[{"id": True}], [{"id": 21}, {"id": 21}], {"items": [{"id": 21}]}, [{"id": index + 1} for index in range(1001)]])
def test_catalog_shape_identity_and_bound_are_loud(rows):
    with pytest.raises(ValueError):
        node.catalog(rows, node.credential_value(CREDENTIAL), "group")


async def test_mismatched_returned_organization_stops_child_read(transport):
    calls, state = transport
    state["payload"] = {"id": 13, "name": "Wrong organization"}
    with pytest.raises(ValueError, match="different organization"):
        await node.request_operation(CREDENTIAL, node.ListUsers())
    assert len(calls) == 1


@pytest.mark.parametrize("context", [{"organization_id": "13"}, {"token": "forged"}, {"_credential_type": node.TYPES[0]}, {"field_scopes": {"user_id": ["32"]}}])
async def test_picker_rejects_forged_private_scope_before_io(transport, context):
    calls, _ = transport
    with pytest.raises(ValueError):
        await node.SlingNode.load_field_options("user_id", CREDENTIAL, context=context)
    assert calls == []


async def test_actual_picker_search_and_no_invented_paging(transport):
    calls, _ = transport
    result = await node.SlingNode.load_field_options("group_id", CREDENTIAL, search="fixture")
    assert result["options"] == [{"value": "21", "label": "Fixture Location", "metadata": {"id": "21", "scope": "token_current_organization"}}]
    assert result["next_page_token"] is None and len(calls) == 2
    with pytest.raises(ValueError, match="no documented pagination"):
        await node.SlingNode.load_field_options("group_id", CREDENTIAL, page_token="1")
    assert len(calls) == 2


@pytest.mark.parametrize("field,value", [("user_id", 31), ("user_id", True), ("organization_id", "13"), ("headers", {"Authorization": "forged"}), ("includeTimesheets", "full")])
def test_raw_config_cannot_override_native_authority(field, value):
    raw = {"config": {"operation": "get_user", "user_id": "31", field: value}, "credentials": CREDENTIAL}
    assert node.SlingNode.validate_config(raw)["valid"] is False
    with pytest.raises(ValueError):
        node.SlingNode.parse_config(raw)
