"""Offline Platform API request, response and manual credential regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import turso_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-turso-platform-token"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/turso/responses.json").read_text())
ORG = {"organization_slug": "my-org"}
DB = {**ORG, "database_name": "my-db"}
GROUP = {**ORG, "group_name": "default"}
CASES = [
    ("list_organizations", {}, "GET", "/v1/organizations", "organizations", None),
    ("list_locations", {}, "GET", "/v1/locations", "locations", None),
    ("get_organization", ORG, "GET", "/v1/organizations/my-org", "organization", None),
    ("list_databases", {**ORG, "group": "default", "parent": "parent-id"}, "GET", "/v1/organizations/my-org/databases", "databases", None),
    ("create_database", {**ORG, "name": "my-db", "group": "default"}, "POST", "/v1/organizations/my-org/databases", "database", {"name": "my-db", "group": "default"}),
    ("get_database", DB, "GET", "/v1/organizations/my-org/databases/my-db", "database", None),
    ("delete_database", DB, "DELETE", "/v1/organizations/my-org/databases/my-db", "deleted_database", None),
    ("get_database_configuration", DB, "GET", "/v1/organizations/my-org/databases/my-db/configuration", "configuration", None),
    ("update_database_configuration", {**DB, "block_writes": False}, "PATCH", "/v1/organizations/my-org/databases/my-db/configuration", "configuration", {"block_writes": False}),
    ("list_database_instances", DB, "GET", "/v1/organizations/my-org/databases/my-db/instances", "instances", None),
    ("get_database_usage", {**DB, "from_time": "2023-01-01T00:00:00Z", "to_time": "2023-02-01T00:00:00Z"}, "GET", "/v1/organizations/my-org/databases/my-db/usage", "usage", None),
    ("get_database_stats", DB, "GET", "/v1/organizations/my-org/databases/my-db/stats", "stats", None),
    ("list_groups", ORG, "GET", "/v1/organizations/my-org/groups", "groups", None),
    ("create_group", {**ORG, "name": "new-group", "location": "aws-us-east-1"}, "POST", "/v1/organizations/my-org/groups", "group", {"name": "new-group", "location": "aws-us-east-1"}),
    ("get_group", GROUP, "GET", "/v1/organizations/my-org/groups/default", "group", None),
    ("delete_group", GROUP, "DELETE", "/v1/organizations/my-org/groups/default", "group", None),
    ("get_group_configuration", GROUP, "GET", "/v1/organizations/my-org/groups/default/configuration", "group_configuration", None),
    ("update_group_configuration", {**GROUP, "delete_protection": False}, "PATCH", "/v1/organizations/my-org/groups/default/configuration", "group_configuration", {"delete_protection": False}),
    ("list_organization_members", ORG, "GET", "/v1/organizations/my-org/members", "members", None),
    ("get_organization_usage", ORG, "GET", "/v1/organizations/my-org/usage", "organization_usage", None),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="turso-test", node_type="automation-turso",
        node_data={"config": config, "credentials": credential or {"credential_type": native.TYPE, "api_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,fixture,body", CASES)
async def test_documented_contract_requests(monkeypatch, operation, config, method, path, fixture, body):
    requests = transport(monkeypatch, httpx.Response(200, json=FIXTURE[fixture]))
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.turso.tech"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    expected_query = {"group": "default", "parent": "parent-id"} if operation == "list_databases" else {"from": config["from_time"], "to": config["to_time"]} if operation == "get_database_usage" else {}
    assert dict(request.url.params) == expected_query
    assert result.get("write_acknowledged", False) == (method != "GET")
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 400, 401, 403, 404, 429, 500])
async def test_error_status_no_retry_redirect_or_secret_leak(monkeypatch, code):
    requests = transport(monkeypatch, httpx.Response(code, json={"error": TOKEN}, headers={"Location": "https://evil.example"}))
    result = await node({"operation": "delete_database", **DB}).execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert TOKEN not in str(result) and len(requests) == 1
    assert result["write_outcome_unknown"] == (code >= 500)


@pytest.mark.asyncio
async def test_provider_rejection_is_preserved_for_connect(monkeypatch):
    transport(monkeypatch, httpx.Response(401, json={"error": "token expired"}))
    result = await node({"operation": "list_organizations"}).execute({})
    assert result["error"] == "token expired" and result["http_status"] == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"error": "refused"}, {"organizations": []}, ["wrong-item"]])
async def test_connection_evidence_rejects_bad_shapes(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    result = await node({"operation": "list_organizations"}).execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_empty_org_list_and_null_query_stats_are_valid(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json=[]))
    assert (await node({"operation": "list_organizations"}).execute({}))["data"] == []
    transport(monkeypatch, httpx.Response(200, json={"top_queries": None}))
    assert (await node({"operation": "get_database_stats", **DB}).execute({}))["data"] is None


@pytest.mark.asyncio
async def test_malformed_json_and_redaction(monkeypatch):
    transport(monkeypatch, httpx.Response(200, content=b"{", headers={"content-type": "application/json"}))
    assert (await node({"operation": "list_organizations"}).execute({}))["status"] == "error"
    transport(monkeypatch, httpx.Response(200, json=[{"name": TOKEN}]))
    assert TOKEN not in str(await node({"operation": "list_organizations"}).execute({}))


def test_manual_credential_and_defaults():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, _ = shape_credential(native.TYPE, {"api_token": "  " + TOKEN + "  "})
    assert not errors and native.TursoAPITokenCredential(**shaped).credential_type == native.TYPE and shaped["api_token"] == TOKEN
    for bad in ("Bearer abc", "https://example.com/token", "<token>", "bad\r\nheader"):
        with pytest.raises(ValidationError):
            native.TursoAPITokenCredential(api_token=bad)
    with pytest.raises(ValidationError):
        native.TursoAPITokenCredential(credential_type="another_api_token", api_token=TOKEN)


@pytest.mark.parametrize("config", [
    {"operation": "get_database", **DB, "database_name": "../secret"},
    {"operation": "get_group", **GROUP, "organization_slug": "foo/bar"},
    {"operation": "update_database_configuration", **DB},
    {"operation": "get_database_usage", **DB, "from_time": "yesterday"},
    {"operation": "get_database_usage", **DB, "from_time": "2023-02-01T00:00:00Z", "to_time": "2023-01-01T00:00:00Z"},
])
def test_invalid_inputs_fail_before_request(config):
    with pytest.raises(Exception):
        node(config)
