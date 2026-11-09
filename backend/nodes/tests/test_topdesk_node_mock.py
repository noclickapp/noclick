"""Contract-shaped transport, manual credential and stateful poll coverage."""
import base64
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import topdesk_node as td

FIXTURE = json.loads((Path(__file__).parent / "fixtures/topdesk/incidents.json").read_text())
INCIDENTS = FIXTURE["body"]
ID = INCIDENTS[0]["id"]


def node(operation, **values):
    return td.TOPdeskNode(node_id="topdesk-test", node_type="automation-topdesk", node_data={},
        config=td.TOPdeskNodeConfig.model_validate({"config": {"operation": operation, **values},
            "credentials": {"base_url": "https://example.topdesk.net", "username": "operator", "application_token": "test-application-token"}}),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")


def transport(monkeypatch, handler):
    monkeypatch.setattr(td, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_create_update_auth_and_omitted_fields(monkeypatch):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(201 if request.method == "POST" else 200, json=INCIDENTS[0])
    transport(monkeypatch, handle)
    await node("create_incident", caller_id=ID, brief_description="Coffee machine is not working", action="some action").execute({})
    await node("update_incident", incident_id=ID, closed=False, operator_id=ID).execute({})
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/tas/api/incidents"
    assert json.loads(seen[0].content) == {"callerLookup": {"id": ID}, "briefDescription": "Coffee machine is not working", "action": "some action", "status": "firstLine"}
    assert seen[1].method == "PATCH"
    assert json.loads(seen[1].content) == {"closed": False, "operator": {"id": ID}}
    assert seen[0].headers["Authorization"] == "Basic " + base64.b64encode(b"operator:test-application-token").decode()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,method,suffix,body", [
    ("get_incident", {"incident_id": ID}, "GET", "/id/" + ID, None),
    ("get_incident_by_number", {"number": "I 2211 016"}, "GET", "/number/I 2211 016", None),
    ("archive_incident", {"incident_id": ID, "reason_name": "Duplicate"}, "PUT", "/id/" + ID + "/archive", {"name": "Duplicate"}),
    ("unarchive_incident", {"incident_id": ID, "unarchive_partials": False}, "PUT", "/id/" + ID + "/unarchive", None),
    ("register_time_spent", {"incident_id": ID, "time_spent": 15, "notes": "Fixed"}, "POST", "/id/" + ID + "/timespent", {"timeSpent": 15, "notes": "Fixed"}),
])
async def test_record_operations(monkeypatch, operation, values, method, suffix, body):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(201 if method == "POST" else 200, json=INCIDENTS[0])
    transport(monkeypatch, handle)
    result = await node(operation, **values).execute({})
    assert result["data"]["id"] == ID
    assert seen[0].method == method
    assert seen[0].url.path == "/tas/api/incidents" + suffix
    assert (json.loads(seen[0].content) if seen[0].content else None) == body
    if operation == "unarchive_incident":
        assert seen[0].url.params["unarchive_partials"] == "false"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,suffix", [
    ("list_actions", "actions"), ("list_requests", "requests"), ("list_progress_trail", "progresstrail"),
    ("list_time_spent", "timespent"),
])
async def test_trail_and_time_reads(monkeypatch, operation, suffix):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=[{"id": ID}])
    transport(monkeypatch, handle)
    assert (await node(operation, incident_id=ID).execute({}))["items"] == [{"id": ID}]
    assert seen[0].url.path.endswith("/id/" + ID + "/" + suffix)
    if operation == "list_progress_trail":
        assert seen[0].headers["Accept"] == "application/x.topdesk-collection-progress-trail-v4+json"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,suffix", list(td._CATALOG.items()) + [("list_operators", "operators/lookup"), ("list_operator_groups", "operatorgroups/lookup")])
async def test_reference_lists(monkeypatch, operation, suffix):
    def handle(request):
        assert request.method == "GET"
        assert request.url.path == "/tas/api/incidents/" + suffix
        data = [{"id": ID, "name": "Example"}]
        return httpx.Response(200, json={"results": data} if suffix.endswith("lookup") else data)
    transport(monkeypatch, handle)
    assert (await node(operation).execute({}))["items"][0]["id"] == ID


@pytest.mark.asyncio
async def test_list_partial_empty_and_auth_rejection(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(206, json=INCIDENTS))
    result = await node("list_incidents", page_start=10, page_size=1).execute({})
    assert result["has_more"] and result["next_offset"] == 11
    transport(monkeypatch, lambda request: httpx.Response(204))
    assert (await node("list_incidents").execute({}))["items"] == []
    transport(monkeypatch, lambda request: httpx.Response(401, text="Unauthorized"))
    with pytest.raises(httpx.HTTPStatusError):
        await node("list_incidents").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_incident", "on_updated_incident"])
async def test_poll_baseline_new_item_update_and_agent(monkeypatch, operation):
    rows = copy.deepcopy(INCIDENTS)
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=rows)
    transport(monkeypatch, handle)
    n = node(operation, query="closed==false")
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        changed, result = mutator(state)
        if changed is not None:
            state = changed
        return result
    monkeypatch.setattr(n, "_update_node_state", update)
    assert (await n.execute({}))["incidents"] == []
    rows.append({**rows[0], "id": "751e0a70-5b2b-572d-8cae-99f52651b6d0"})
    result = await n.execute({})
    assert len(result["incidents"]) == 1
    event = td.TOPdeskNode.resolve_agent_event(result)
    assert "Example Caller" in event["text"] and "some request" in event["text"] and rows[1]["id"] in event["text"]
    assert n.trigger_emitted_event(result)
    rows[0]["modificationDate"] = "2026-01-01T12:00:00Z"
    result = await n.execute({})
    assert len(result["incidents"]) == (1 if operation == "on_updated_incident" else 0)
    assert requests[0].url.params["query"] == "closed==false"
    assert requests[0].url.params["all"] == "true"
    assert (await n.execute({}))["incidents"] == []
    assert td.TOPdeskNode.resolve_agent_event({"incidents": []}) is None


@pytest.mark.asyncio
async def test_poll_paginates_and_does_not_advance_state_on_overflow(monkeypatch):
    seen = []
    def handle(request):
        seen.append(int(request.url.params["pageStart"]))
        return httpx.Response(206, json=INCIDENTS)
    transport(monkeypatch, handle)
    n = node("on_updated_incident")
    with pytest.raises(ValueError, match="5,000"):
        await n.execute({})
    assert seen == list(range(0, 5000, 100))


@pytest.mark.parametrize("field,value", [("base_url", "http://example.topdesk.net"), ("username", "a:b"), ("application_token", "https://example.com/key")])
def test_invalid_manual_credentials(field, value):
    values = {"base_url": "https://example.topdesk.net", "username": "operator", "application_token": "test-token", field: value}
    with pytest.raises(ValidationError):
        td.TOPdeskCredential(**values)


def test_manual_credential_default_and_uuid_validation():
    credential = td.TOPdeskCredential(base_url="example.topdesk.net/tas/secure", username="operator", application_token="test-token")
    assert credential.credential_type == "topdesk_application_token"
    assert credential.base_url == "https://example.topdesk.net"
    with pytest.raises(ValidationError):
        td.UpdateIncident(incident_id=ID, operator_id="bad-id")
    with pytest.raises(ValidationError, match="at least one"):
        td.UpdateIncident(incident_id=ID)
