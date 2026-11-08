"""Exercise Rootly through the native operation seam with fixture HTTP only.

Wire assertions pin JSON:API media, resource names, update verbs and pagination;
failure cases ensure credentials and uncertain writes are handled correctly.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import rootly_node as rootly
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "rootly_api_key", "api_key": "rootly-fixture-secret-123"}
USER = "00000000-0000-4000-8000-000000000001"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/rootly/resources.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.rootly.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert request.headers["Accept"] == rootly.MEDIA_TYPE
        assert request.headers["Content-Type"] == rootly.MEDIA_TYPE
        assert AUTH["api_key"] not in str(request.url)
        status, body = replies.pop(0)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body, headers={"Content-Type": rootly.MEDIA_TYPE})

    native = ssrf.guarded_async_client
    monkeypatch.setattr(rootly, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=None):
    return await run_node_operation(node_type="automation-rootly", operation=operation,
                                    arguments=arguments or {}, credential_data=auth or AUTH, user_id=USER)


CASES = [
    ("list_incidents", {}, "GET", "/v1/incidents", "incidents", True),
    ("get_incident", {"incident_id": "inc1"}, "GET", "/v1/incidents/inc1", "incidents", False),
    ("create_incident", {"title": "Database unavailable"}, "POST", "/v1/incidents", "incidents", False),
    ("update_incident", {"incident_id": "inc1", "status": "resolved"}, "PUT", "/v1/incidents/inc1", "incidents", False),
    ("delete_incident", {"incident_id": "inc1"}, "DELETE", "/v1/incidents/inc1", "incidents", False),
    ("list_incident_events", {"incident_id": "inc1"}, "GET", "/v1/incidents/inc1/events", "incident_events", True),
    ("create_incident_event", {"incident_id": "inc1", "event": "Mitigation deployed", "visibility": "internal"}, "POST", "/v1/incidents/inc1/events", "incident_events", False),
    ("list_action_items", {"incident_id": "inc1"}, "GET", "/v1/incidents/inc1/action_items", "incident_action_items", True),
    ("create_action_item", {"incident_id": "inc1", "summary": "Add failover"}, "POST", "/v1/incidents/inc1/action_items", "incident_action_items", False),
    ("get_action_item", {"action_item_id": "act1"}, "GET", "/v1/action_items/act1", "incident_action_items", False),
    ("update_action_item", {"action_item_id": "act1", "status": "done"}, "PUT", "/v1/action_items/act1", "incident_action_items", False),
    ("list_teams", {}, "GET", "/v1/teams", "groups", True),
    ("get_team", {"team_id": "team1"}, "GET", "/v1/teams/team1", "groups", False),
    ("list_services", {}, "GET", "/v1/services", "services", True),
    ("get_service", {"service_id": "svc1"}, "GET", "/v1/services/svc1", "services", False),
    ("list_severities", {}, "GET", "/v1/severities", "severities", True),
    ("get_severity", {"severity_id": "sev1"}, "GET", "/v1/severities/sev1", "severities", False),
    ("list_users", {}, "GET", "/v1/users", "users", True),
    ("get_user", {"user_id": "123"}, "GET", "/v1/users/123", "users", False),
    ("get_current_user", {}, "GET", "/v1/users/me", "users", False),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,kind,many", CASES)
async def test_native_operations(transport, operation, arguments, method, path, kind, many):
    requests, replies = transport
    record = FIXTURE[kind]
    payload = {"data": [record] if many else record}
    if many:
        payload.update(links={"next": None}, meta={"next_page": None})
    replies.append((201 if method == "POST" else 200, payload))
    result = await run(operation, arguments)
    assert result["success"] is True
    assert len(requests) == 1 and replies == []
    request = requests[0]
    assert (request.method, request.url.path) == (method, path)
    if method in {"POST", "PUT"}:
        attrs = {k: v for k, v in arguments.items() if k not in {"incident_id", "action_item_id"}}
        assert json.loads(request.content) == {"data": {"type": kind, "attributes": attrs}}
    if many:
        assert dict(request.url.params) == {"page[number]": "1", "page[size]": "20"}
        assert result["data"][0]["id"] == record["id"]
        assert result["pagination"]["meta"]["next_page"] is None


@pytest.mark.asyncio
async def test_filters_paging_and_no_following_provider_links(transport):
    requests, replies = transport
    replies.append((200, {"data": [], "links": {"next": "https://elsewhere.test/?steal=1"}, "meta": {"next_page": 4}}))
    result = await run("list_incidents", {"page_number": 3, "page_size": 10, "search": "Database", "status": "started", "severity_id": "sev1"})
    assert dict(requests[0].url.params) == {"page[number]": "3", "page[size]": "10", "filter[search]": "Database", "filter[status]": "started", "filter[severity_id]": "sev1"}
    assert result["pagination"]["meta"]["next_page"] == 4
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_incident_idempotency_and_empty_array_update(transport):
    requests, replies = transport
    replies.extend([(201, {"data": FIXTURE["incidents"]}), (200, {"data": FIXTURE["incidents"]})])
    await run("create_incident", {"title": "Database unavailable", "idempotency_key": "creation-123"})
    assert requests[0].headers["Idempotency-Key"] == "creation-123"
    assert "idempotency_key" not in json.loads(requests[0].content)["data"]["attributes"]
    await run("update_incident", {"incident_id": "inc1", "service_ids": [], "group_ids": []})
    assert json.loads(requests[1].content)["data"]["attributes"] == {"service_ids": [], "group_ids": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_error_verbatim_redacted_and_no_retries(transport, status):
    requests, replies = transport
    replies.append((status, {"error": "Rejected " + AUTH["api_key"]}))
    result = await run("list_incidents")
    assert result["success"] is False and result["http_status"] == status
    assert "Rejected" in result["message"] and AUTH["api_key"] not in json.dumps(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"errors": [{"detail": "Failed"}]}, {"data": {}}, {"data": [{"type": "incidents", "id": "inc1", "attributes": None}]}])
async def test_invalid_collection_cannot_prove_connection(transport, payload):
    transport[1].append((200, payload))
    result = await run("list_incidents")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_write_timeout_and_unreadable_ack_are_uncertain(transport):
    requests, replies = transport
    replies.extend([(200, httpx.ReadTimeout("fixture timeout")), (201, {"invalid": True})])
    for _ in range(2):
        result = await run("create_incident", {"title": "Database unavailable"})
        assert result["status"] == "unknown" and result["success"] is False
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_server_error_write_is_uncertain(transport):
    transport[1].append((503, {"error": "Unavailable"}))
    result = await run("create_incident", {"title": "Database unavailable"})
    assert result["status"] == "unknown" and result["http_status"] == 503
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_integer_assignee_and_action_fields(transport):
    requests, replies = transport
    replies.append((201, {"data": FIXTURE["incident_action_items"]}))
    fields = {"summary": "Add failover", "assigned_to_user_id": 123, "kind": "follow_up", "priority": "high", "status": "open", "due_date": "2026-11-30"}
    await run("create_action_item", {"incident_id": "inc1", **fields})
    assert json.loads(requests[0].content)["data"]["attributes"] == fields


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["..", ".", "a/b", "a%2Fb", "a?x=1", "https://evil.test", "x\ny"])
async def test_invalid_path_ids_before_http(transport, bad):
    with pytest.raises(ValueError):
        await run("get_incident", {"incident_id": bad})
    assert not transport[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", [
    {"credential_type": "unrelated_api_key", "api_key": "fixture-secret-123"},
    {"credential_type": None, "api_key": "fixture-secret-123"},
    {"credential_type": "rootly_api_key", "api_key": "Bearer fixture-secret-123"},
    {"credential_type": "rootly_api_key", "api_key": "https://evil.test"},
])
async def test_invalid_credentials_before_http(transport, auth):
    with pytest.raises(ValueError):
        await run("list_incidents", auth=auth)
    assert not transport[0]


def test_credential_shaping_and_evidence_declaration():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential("rootly_api_key", {**AUTH, "api_key": "  " + AUTH["api_key"] + "\n"})
    assert not errors and shaped["api_key"] == AUTH["api_key"]
    assert resolved[0] == "automation-rootly"
    assert rootly.RootlyNode.connection_evidence.operation == "list_incidents"


def test_parse_and_validate_agree_with_ui_metadata_and_foreign_family():
    data = {"config": {"operation": "list_incidents", "credentialIds": {"rootly_api_key": "saved"}}, "credentials": AUTH}
    assert rootly.RootlyNode.validate_config(data)["valid"] is True
    assert rootly.RootlyNode.parse_config(data).config.page_number == 1
    data["credentials"] = {**AUTH, "credential_type": "unrelated_api_key"}
    assert rootly.RootlyNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError):
        rootly.RootlyNode.parse_config(data)
