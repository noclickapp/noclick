"""Exercise SquadCast through the real node factory with intercepted HTTP.

These tests cover each operation's wire contract, regional token exchange,
manual credential shaping, provider failures and credential redaction.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import squadcast_node as sc
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "squadcast_api_token", "api_token": "fixture-refresh-token"}
CASES = [
    ("get_incident", {"incident_id": "i1"}, "GET", "/v3/incidents/i1", None, {}),
    ("acknowledge_incident", {"incident_id": "i1"}, "POST", "/v3/incidents/i1/acknowledge", None, {}),
    ("resolve_incident", {"incident_id": "i1", "resolution_message": "Recovered"}, "POST", "/v3/incidents/i1/resolve", {"resolution_reason": {"message": "Recovered"}}, {}),
    ("reassign_incident", {"incident_id": "i1", "assignee_id": "u1", "assignee_type": "user"}, "POST", "/v3/incidents/i1/reassign", {"reassignTo": {"id": "u1", "type": "user"}}, {}),
    ("update_incident_priority", {"incident_id": "i1", "priority": "P2"}, "PATCH", "/v3/incidents/i1/priority", {"priority": "P2"}, {}),
    ("create_note", {"incident_id": "i1", "message": "Investigating"}, "POST", "/v3/incidents/i1/warroom", {"message": "Investigating", "attachments": []}, {}),
    ("list_notes", {"incident_id": "i1"}, "GET", "/v3/incidents/i1/warroom", None, {}),
    ("list_incident_events", {"incident_id": "i1", "offset": 2, "deduped": "false"}, "GET", "/v3/incidents/i1/events", None, {"offset": "2", "limit": "10", "sort": "desc", "deduped": "false"}),
    ("list_services", {"owner_id": "t1", "name": "API"}, "GET", "/v3/services", None, {"owner_id": "t1", "name": "API"}),
    ("get_service", {"service_id": "s1"}, "GET", "/v3/services/s1", None, {}),
    ("create_service", {"name": "API", "owner_id": "t1", "escalation_policy_id": "ep1"}, "POST", "/v3/services", {"name": "API", "owner_id": "t1", "escalation_policy_id": "ep1"}, {"owner_id": "t1"}),
    ("update_service", {"service_id": "s1", "description": "Changed"}, "PUT", "/v3/services/s1", {"description": "Changed"}, {}),
    ("list_teams", {}, "GET", "/v3/teams", None, {}),
    ("get_team", {"team_id": "t1"}, "GET", "/v3/teams/t1", None, {}),
    ("list_team_members", {"team_id": "t1"}, "GET", "/v3/teams/t1/members", None, {}),
    ("list_users", {}, "GET", "/v3/users", None, {}),
    ("get_user", {"user_id": "u1"}, "GET", "/v3/users/u1", None, {}),
    ("list_schedules", {"team_id": "t1", "cursor": "opaque+/==", "my_on_call": False}, "GET", "/v4/schedules", None, {"teamID": "t1", "pageSize": "20", "cursor": "opaque+/==", "myOnCall": "false"}),
    ("get_schedule", {"schedule_id": "123"}, "GET", "/v4/schedules/123", None, {}),
    ("list_runbooks", {}, "GET", "/v3/runbooks", None, {}),
]


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(sc, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=None):
    node = NodeFactory.create_node(node_id="squadcast-test", node_type="automation-squadcast",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": auth or AUTH})
    return await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["us", "eu"])
@pytest.mark.parametrize("operation,arguments,method,path,body,query", CASES)
async def test_squadcast_each_operation(transport, region, operation, arguments, method, path, body, query):
    requests, replies = transport
    fixture = json.loads((Path(__file__).parent / "fixtures/squadcast/responses.json").read_text())
    response = fixture["events"] if operation == "list_incident_events" else fixture["list"] if operation.startswith("list_") else fixture["record"]
    if operation == "list_schedules": response = fixture["schedules"]
    replies.extend([(200, fixture["auth"]), (201 if operation in {"create_note", "create_service"} else 200, response)])
    result = await run(operation, arguments, {**AUTH, "region": region})
    assert result["status"] == "success"
    assert result["data"] == response["data"]
    if "meta" in response: assert result["meta"] == response["meta"]
    if "pageInfo" in response: assert result["pageInfo"] == response["pageInfo"]
    assert len(requests) == 2 and not replies
    suffix = ".eu" if region == "eu" else ""
    auth, request = requests
    assert str(auth.url) == f"https://auth{suffix}.squadcast.com/oauth/access-token"
    assert auth.method == "GET" and auth.headers["X-Refresh-Token"] == AUTH["api_token"]
    assert "Authorization" not in auth.headers
    assert request.url.host == f"api{suffix}.squadcast.com"
    assert request.method == method and request.url.path == path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert request.headers["Authorization"] == "Bearer fixture-access-token"
    assert "X-Refresh-Token" not in request.headers
    assert AUTH["api_token"] not in str(request.url)
    assert "fixture-access-token" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("at_auth", [True, False])
async def test_squadcast_provider_rejection_preserved_and_secrets_redacted(transport, at_auth):
    requests, replies = transport
    if not at_auth: replies.append((200, {"data": {"access_token": "fixture-access-token"}}))
    replies.append((401, {"meta": {"error_message": "Token rejected: fixture-refresh-token"}}))
    result = await run("list_teams")
    assert result["status"] == "error" and result["http_status"] == 401
    assert result["error"] == "Token rejected: [redacted]"
    assert len(requests) == (1 if at_auth else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_body", [{"data": {}}, {"data": "wrong"}, {"data": {"access_token": "bad\ntoken"}}, {"error": "denied"}])
async def test_squadcast_bad_exchange_does_not_make_resource_request(transport, auth_body):
    requests, replies = transport
    replies.append((200, auth_body))
    assert (await run("list_teams"))["status"] == "error"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_squadcast_invalid_evidence_shape_is_not_success(transport):
    _, replies = transport
    replies.extend([(200, {"data": {"access_token": "fixture-access-token"}}), (200, {"data": {"name": "not a list"}})])
    assert (await run("list_teams"))["status"] == "error"


def test_squadcast_credential_connect_default_and_evidence():
    from nodes.core.credential_connect import shape_credential, typed_fields
    shaped, errors, _ = shape_credential("squadcast_api_token", {"api_token": AUTH["api_token"]})
    assert not errors
    assert sc.SquadCastAPITokenCredential.model_validate(shaped).credential_type == "squadcast_api_token"
    assert {field["name"] for field in typed_fields("squadcast_api_token")} >= {"api_token"}
    assert sc.SquadCastNode.connection_evidence.operation == "list_teams"


@pytest.mark.parametrize("value", ["../other", "id?token=x", "https://evil.example", "a/b", "a#b"])
def test_squadcast_path_ids_cannot_change_route(value):
    with pytest.raises(ValidationError): sc.GetIncident(incident_id=value)


def test_squadcast_required_inputs_and_nonempty_update():
    for cls, arguments in [(sc.ListServices, {}), (sc.ListSchedules, {}), (sc.CreateService, {"name": "API"}), (sc.UpdateService, {"service_id": "s1"})]:
        with pytest.raises(ValidationError): cls(**arguments)


@pytest.mark.asyncio
async def test_squadcast_connection_evidence_names_account_teams(transport):
    from nodes.core.connection_evidence import collect_evidence
    _, replies = transport
    replies.extend([(200, {"data": {"access_token": "fixture-access-token"}}),
                    (200, {"data": [{"id": "t1", "name": "Production Operations"}]})])
    evidence = await collect_evidence(node_type="automation-squadcast",
        user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert evidence.reachable is True
    assert [sample.label for sample in evidence.samples] == ["Production Operations"]
