"""Exercise native factory operations against captured HTTP requests, without an account."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import samanage_node as native
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "samanage_api_token", "api_token": "synthetic-samanage-opaque-token", "region": "us"}
RECORDS = json.loads((Path(__file__).parent / "fixtures/samanage/responses.json").read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    def respond(request):
        requests.append(request)
        return replies.pop(0)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, replies

async def run(config, credential=None):
    node = NodeFactory.create_node(node_id="fixture", node_type="automation-samanage",
        node_data={"config": config, "credentials": credential or AUTH})
    return await node.execute({})

@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["incident", "user", "solution", "problem", "change"])
@pytest.mark.parametrize("action", ["list", "get", "create", "update"])
async def test_all_operations_map_to_one_contract_request(wire, resource, action):
    requests, replies = wire
    op = action + "_" + resource + ("s" if action == "list" else "")
    config = {"operation": op}
    if action in {"get", "update"}: config[resource + "_id"] = "1"
    if action in {"create", "update"}: config["name"] = RECORDS[resource]["name"]
    if action == "create" and resource == "user": config["email"] = "john.doe@email.com"
    if action == "create" and resource == "change": config["change_type"] = 1
    row = RECORDS[resource]
    body = [row] if action == "list" else row if resource == "incident" else {resource: row}
    replies.append(httpx.Response(200, json=body))
    result = await run(config)
    assert result["status"] == "success"
    assert result["items"] == [row] if action == "list" else result["item"] == row
    assert len(requests) == 1
    req = requests[0]
    assert req.method == {"list": "GET", "get": "GET", "create": "POST", "update": "PUT"}[action]
    assert req.url.path == "/" + resource + "s" + ("/1" if action in {"get", "update"} else "")
    assert req.headers["X-Samanage-Authorization"] == "Bearer " + AUTH["api_token"]
    assert req.headers["Accept"] == "application/vnd.samanage.v2.1+json"
    if action in {"create", "update"}:
        expected = {k:v for k,v in config.items() if k not in {"operation", resource + "_id"}}
        assert json.loads(req.content) == {resource: expected}
    assert AUTH["api_token"] not in str(result)

@pytest.mark.asyncio
@pytest.mark.parametrize("region,host", [("us", "api.samanage.com"), ("eu", "apieu.samanage.com"), ("apj", "apiau.samanage.com")])
async def test_region_and_pagination(wire, region, host):
    wire[1].append(httpx.Response(200, json=[RECORDS["incident"]], headers={"Link": '<https://' + host + '/incidents.json?page=3>; rel="next"'}))
    result = await run({"operation": "list_incidents", "page": 2, "per_page": 10}, {**AUTH, "region": region})
    assert wire[0][0].url.host == host and dict(wire[0][0].url.params) == {"page": "2", "per_page": "10"}
    assert result["next_page"] == 3 and result["has_more"] is True

@pytest.mark.asyncio
async def test_person_mapping_and_id_only_update(wire):
    wire[1].append(httpx.Response(200, json={"id": 1, "name": "Incident Name"}))
    await run({"operation": "update_incident", "incident_id": "1", "assignee_id": "2", "state_id": "3", "requester_email": "john.doe@email.com"})
    assert json.loads(wire[0][0].content) == {"incident": {"assignee_id": "2", "state_id": "3", "requester": {"email": "john.doe@email.com"}}}

@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 429, 500])
async def test_errors_and_echoed_secrets(wire, code):
    wire[1].append(httpx.Response(code, text="rejected " + AUTH["api_token"]))
    result = await run({"operation": "list_incidents"})
    assert result["status"] == "error" and result["http_status"] == code
    assert AUTH["api_token"] not in str(result) and "rejected" in result["error"]

@pytest.mark.asyncio
async def test_pagination_rejects_foreign_hosts_and_stalled_pages(wire):
    for url in ["https://evil.test/incidents?page=2", "https://api.samanage.com/users?page=2", "https://api.samanage.com/incidents?page=1"]:
        wire[1].append(httpx.Response(200, json=[], headers={"Link": '<' + url + '>; rel="next"'}))
        with pytest.raises(ValueError): await run({"operation": "list_incidents"})
    assert len(wire[0]) == 3

@pytest.mark.asyncio
async def test_empty_account_is_valid_evidence_and_total_page_header(wire):
    wire[1].append(httpx.Response(200, json=[]))
    assert (await run({"operation": "list_incidents"}))["items"] == []
    wire[1].append(httpx.Response(200, json=[RECORDS["user"]], headers={"X-Total-Pages": "2"}))
    assert (await run({"operation": "list_users"}))["next_page"] == 2

@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["<html>login</html>", '{"errors": ["denied"]}'])
async def test_nonjson_and_error_envelopes(wire, body):
    wire[1].append(httpx.Response(200, text=body))
    assert (await run({"operation": "list_incidents"}))["status"] == "error"

@pytest.mark.parametrize("resource_id", ["../users", "0", "1/2", "https://evil.test", "-1"])
def test_reject_path_injection(resource_id):
    with pytest.raises(ValueError): native.SamanageGetIncidentConfig(incident_id=resource_id)

def test_connect_defaults_and_required_create_fields():
    assert native.SamanageTokenCredential(api_token=AUTH["api_token"]).credential_type == "samanage_api_token"
    for cls in [native.SamanageCreateUserConfig, native.SamanageCreateChangeConfig]:
        with pytest.raises(ValueError): cls(name="Name")
    with pytest.raises(ValueError): native.SamanageUpdateIncidentConfig(incident_id="1")
    with pytest.raises(ValueError): native.SamanageTokenCredential(api_token=AUTH["api_token"], region="https://evil.test")
