"""VolunteerHub routes, query modes and write payloads through the real factory."""
import base64
import json
from pathlib import Path

import httpx
import pytest

from nodes import volunteerhub_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

USER = "88fb2de6-ed13-451d-a2c9-7205cac19f66"
GROUP = "6776c7aa-5a82-4a70-87da-3fdbcd6692d6"
CREDENTIAL = {"credential_type": "volunteerhub_basic", "site_url": "myorganization",
    "username": "fixture-user", "password": "fixture-pass"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="volunteerhub-fixture", node_type="automation-volunteerhub",
        node_data={"config": config, "credentials": CREDENTIAL})


def mock(monkeypatch, data, status=200, headers=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=data, headers=headers)
    client_class = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return client_class(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(native.ROUTES))
async def test_all_ten_contract_routes_and_auth(monkeypatch, operation):
    config = {"operation": operation}
    if operation == "get_event": config["event_id"] = USER
    if operation == "get_user" or operation.endswith("memberships"): config["user_id"] = USER
    if operation.endswith("memberships"): config["user_group_uids"] = [GROUP]
    if operation == "list_donations": config["uids"] = [USER, GROUP]
    body = [] if operation.startswith("list_") else {"Name": "Test Organization"}
    if operation.endswith("memberships"):
        body = {("AddedUserGroupUids" if operation.startswith("add_") else "RemovedUserGroupUids"): [GROUP]}
    requests = mock(monkeypatch, body)
    result = await node(config).execute({})
    assert result["data"] == body and len(requests) == 1
    request = requests[0]
    method, path = native.ROUTES[operation]
    assert request.method == method
    assert request.url.path == path.format(user_id=USER, event_id=USER)
    assert request.url.host == "myorganization.volunteerhub.com"
    assert request.headers["authorization"] == "Basic " + base64.b64encode(b"fixture-user:fixture-pass").decode()
    assert request.headers["accept"] == "application/json"
    if operation.startswith("list_"):
        assert request.url.params["page"] == "0" and request.url.params["pageSize"] == "50"
    if operation == "list_donations":
        assert request.url.params.get_list("uids") == [USER, GROUP]
        assert request.url.params["query"] == "UserUids"
    if operation.endswith("memberships"):
        assert json.loads(request.content) == {"UserGroupUids": [GROUP]}
        assert not request.url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,query,fields,expected", [
    ("list_events", "Version", {"earliest_version": 42}, {"earliestVersion": "42"}),
    ("list_events", "Time", {"earliest_time": "2020-01-05T00:00:00Z", "latest_time": "2020-01-07T00:00:00Z"}, {"earliestTime": "2020-01-05T00:00:00Z", "latestTime": "2020-01-07T00:00:00Z"}),
    ("list_users", "LastUpdate", {"earliest_last_update": "2000-01-01T00:00:00Z"}, {"earliestLastUpdate": "2000-01-01T00:00:00Z"}),
    ("list_users", "Version", {"earliest_version": 5}, {"earliestVersion": "5"}),
])
async def test_query_modes_and_one_page_pagination(monkeypatch, operation, query, fields, expected):
    requests = mock(monkeypatch, [{"Name": "one"}, {"Name": "two"}])
    result = await node({"operation": operation, "query": query, "page": 3, "page_size": 2, **fields}).execute({})
    assert result["next_page"] == 4 and len(requests) == 1
    assert dict(requests[0].url.params) == {"page": "3", "pageSize": "2", "query": query, **expected}


@pytest.mark.asyncio
async def test_documented_organization_example_names_account(monkeypatch):
    body = json.loads((Path(__file__).parent / "fixtures/volunteerhub/organization.json").read_text())
    mock(monkeypatch, body)
    result = await node({"operation": "get_organization"}).execute({})
    assert result["data"]["Name"] == "Test Organization"
    evidence = native.VolunteerHubNode.connection_evidence
    assert evidence.identity_operation == "get_organization" and evidence.identity_keys == ("Name",)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_errors_preserve_provider_rejection_and_never_retry(monkeypatch, status):
    requests = mock(monkeypatch, {"detail": "Access denied fixture-pass"}, status=status,
        headers={"Location": "https://other.example/"})
    result = await node({"operation": "get_organization"}).execute({})
    assert result == {"status": "error", "status_code": status, "http_status": status, "error": "Access denied [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reachable", [(401, False), (403, False), (500, None)])
async def test_connect_distinguishes_rejections_from_provider_outages(monkeypatch, status, reachable):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    mock(monkeypatch, {"title": "Request refused"}, status=status)
    async def run(**kwargs):
        assert kwargs["operation"] == "get_organization"
        return await node({"operation": kwargs["operation"]}).execute({})
    monkeypatch.setattr(run_op, "run_node_operation", run)
    evidence = await collect_evidence(node_type="automation-volunteerhub", user_id="fixture-user",
        pool=None, credential_data=CREDENTIAL)
    assert evidence.reachable is reachable


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("get_user", []), ("list_users", {}), ("list_users", ["wrong"]), ("get_user", {"detail": "denied"})])
async def test_malformed_and_error_responses_fail(monkeypatch, operation, body):
    mock(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": operation, **({"user_id": USER} if operation == "get_user" else {})}).execute({})


@pytest.mark.parametrize("site", ["http://myorganization.volunteerhub.com", "https://volunteerhub.com.evil.test", "https://myorganization.volunteerhub.com/api", "https://user@myorganization.volunteerhub.com", "https://myorganization.volunteerhub.com:443", "https://127.0.0.1"])
def test_credential_refuses_foreign_or_noncanonical_hosts(site):
    with pytest.raises(ValueError):
        native.VolunteerHubBasicCredential.model_validate({**CREDENTIAL, "site_url": site})


@pytest.mark.parametrize("config", [
    {"operation": "get_user", "user_id": "../bad"},
    {"operation": "list_users", "page_size": 51},
    {"operation": "list_events", "page": True},
    {"operation": "list_events", "query": "Time"},
    {"operation": "list_users", "query": "LastUpdate"},
    {"operation": "list_donations", "uids": []},
    {"operation": "add_user_group_memberships", "user_id": USER, "user_group_uids": []},
])
def test_invalid_configs(config):
    with pytest.raises(ConfigValidationError):
        native.VolunteerHubNode.parse_config({"config": config, "credentials": CREDENTIAL})


def test_manual_credential_has_default_type_and_only_user_entered_requirements():
    schema = native.VolunteerHubBasicCredential.model_json_schema()
    assert schema["properties"]["credential_type"]["default"] == "volunteerhub_basic"
    assert set(schema["required"]) == {"site_url", "username", "password"}
