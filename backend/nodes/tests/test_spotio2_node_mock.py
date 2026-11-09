"""Exercise SPOTIO's native factory and real HTTP serialization offline.

The fixtures preserve published response examples; request assertions check
wire names independently of the implementation's operation dispatch table.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import spotio2_node as native
from nodes.core.registry import NodeFactory
from utils import ssrf

TOKEN = "synthetic-spotio-token-123"
FIXTURES = Path(__file__).parent / "fixtures/spotio2"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="spotio-test", node_type="automation-spotio2", node_data={
        "config": config, "credentials": {"credential_type": native.FAMILY, "api_token": TOKEN},
    })


def transport(monkeypatch, payload=None, status=200, raw=None):
    requests = []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=payload) if raw is None else httpx.Response(status, content=raw)
    real = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: real(**kw, transport=httpx.MockTransport(reply)))
    return requests


CASES = [
    ("list_users", {"territory_ids": "t1,t2"}, "GET", "/api/users", {"territoryIds": "t1,t2"}, None),
    ("list_teams", {}, "GET", "/api/Teams/all", {}, None),
    ("get_team", {"team_id": 3}, "GET", "/api/Teams/3", {}, None),
    ("list_territories", {}, "GET", "/api/Territories/all", {}, None),
    ("get_territory", {"territory_id": "t1"}, "GET", "/api/Territories/t1", {}, None),
    ("list_record_types", {}, "GET", "/api/workflow/dataObjects", {}, None),
    ("get_record_type", {"type_id": 1}, "GET", "/api/workflow/dataObjects/1", {}, None),
    ("list_activity_templates", {}, "GET", "/api/workflow/activityTemplates", {}, None),
    ("search_records", {"query": "John", "scroll_id": "page-2", "type_id": 1, "page_size": 50}, "GET", "/api/DataObjectsSearch/simple", {"q": "John", "scrollId": "page-2", "typeId": "1", "pageSize": "50"}, None),
    ("get_record", {"record_id": "r1"}, "GET", "/api/DataObjects/r1", {}, None),
    ("get_record_by_external_id", {"external_id": "crm-123"}, "GET", "/api/DataObjects/external/crm-123", {}, None),
    ("create_record", {"type_id": 1, "owner_id": 2, "fields": [{"fieldId": "name", "value": "John"}]}, "POST", "/api/DataObjects", {}, {"dataObject": {"typeId": 1, "ownerId": 2, "fields": [{"fieldId": "name", "value": "John"}]}}),
    ("update_record", {"record_id": "r1", "stage_id": 7, "source": "CRM"}, "PATCH", "/api/DataObjects/r1/jsonp", {}, [{"op": "add", "path": "/stageId", "value": 7}, {"op": "add", "path": "/source", "value": "CRM"}]),
    ("delete_record", {"record_id": "r1"}, "DELETE", "/api/DataObjects/r1", {}, {"mode": "Delete", "permanently": False}),
    ("create_activity", {"record_id": "r1", "notes": "Visited"}, "POST", "/api/v2/activities", {}, {"dataObjectId": "r1", "type": "Note", "notes": "Visited", "done": False, "isNote": True}),
    ("get_activity", {"activity_id": "a1"}, "GET", "/api/v2/activities/a1", {}, None),
    ("list_activities", {"scroll_id": "next", "start_date": "2026-11-01T10:00:00Z", "territory_id": "t1"}, "GET", "/api/v2/activities/feed", {"ScrollId": "next", "StartDate": "2026-11-01T10:00:00Z", "TerritoryId": "t1"}, None),
    ("create_appointment", {"record_id": "r1", "owner_id": "2", "date": "2026-11-10T10:00:00Z", "duration": 60, "title": "Visit"}, "POST", "/api/v2/appointments", {}, {"dataObjectId": "r1", "ownerId": "2", "date": "2026-11-10T10:00:00Z", "duration": 60, "title": "Visit", "sendInvitation": False}),
    ("get_appointment", {"appointment_id": "a1"}, "GET", "/api/v2/appointments/a1", {}, None),
    ("list_record_appointments", {"record_id": "r1", "scroll_id": "next"}, "GET", "/api/DataObjects/r1/appointments/upcoming", {"scrollId": "next"}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query,body", CASES)
async def test_spotio2_requests(monkeypatch, operation, config, method, path, query, body):
    requests = transport(monkeypatch, payload={"id": "r1"})
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.spotio2.com" and request.url.scheme == "https"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(request.url)
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    if method == "PATCH":
        assert request.headers["Content-Type"] == "application/json-patch+json"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,config", [("activity", {"operation": "get_activity", "activity_id": "2163003"}), ("appointment", {"operation": "get_appointment", "appointment_id": "2163003"})])
async def test_spotio2_documented_response(monkeypatch, name, config):
    data = json.loads((FIXTURES / (name + ".json")).read_text())
    transport(monkeypatch, payload=data)
    assert (await node(config).execute({}))["data"] == data


@pytest.mark.asyncio
async def test_spotio2_scroll_preserved_and_redaction(monkeypatch):
    transport(monkeypatch, payload={"items": [{"id": "r1", "name": TOKEN}], "scrollId": "next-page"})
    result = await node({"operation": "search_records"}).execute({})
    assert result["data"]["scrollId"] == "next-page" and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 404, 429, 500])
async def test_spotio2_failure(monkeypatch, status):
    requests = transport(monkeypatch, payload={"message": "Rejected " + TOKEN}, status=status)
    result = await node({"operation": "list_users"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
async def test_spotio2_empty_delete(monkeypatch):
    transport(monkeypatch, status=204, raw=b"")
    assert (await node({"operation": "delete_record", "record_id": "r1"}).execute({}))["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b"<html>Oops</html>", b'"unexpected"'])
async def test_spotio2_invalid_response(monkeypatch, raw):
    transport(monkeypatch, raw=raw)
    with pytest.raises(ValueError, match="SPOTIO returned"):
        await node({"operation": "list_users"}).execute({})


@pytest.mark.asyncio
async def test_spotio2_error_envelope(monkeypatch):
    transport(monkeypatch, payload={"errors": {"field": "invalid"}})
    assert (await node({"operation": "list_users"}).execute({}))["status"] == "error"


@pytest.mark.parametrize("identifier", ["../abc", "..", ".", "a/b", "a?x=1", "https://evil.test"])
def test_spotio2_path_validation(identifier):
    with pytest.raises(ValueError):
        node({"operation": "get_record", "record_id": identifier})


def test_spotio2_empty_patch_refused():
    with pytest.raises(ValueError, match="Supply at least one"):
        node({"operation": "update_record", "record_id": "r1"})


def test_spotio2_manual_credential():
    assert native.Spotio2TokenCredential(api_token="  " + TOKEN + "\n").credential_type == native.FAMILY
    for token in ["https://example.test/key", "Bearer abc", "<token>"]:
        with pytest.raises(ValueError):
            native.Spotio2TokenCredential(api_token=token)


def test_spotio2_requires_timezone():
    with pytest.raises(ValueError):
        node({"operation": "create_appointment", "record_id": "r1", "owner_id": "2", "date": "2026-11-10T10:00:00", "duration": 60, "title": "Visit"})


def test_spotio2_refuses_foreign_credentials():
    data = {"config": {"operation": "list_users"}, "credentials": {"credential_type": "other_api_token", "api_token": TOKEN}}
    with pytest.raises(ValueError, match="SPOTIO"):
        native.Spotio2Node.parse_config(data)
    assert native.Spotio2Node.validate_config(data)["valid"] is False
