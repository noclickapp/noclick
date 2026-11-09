"""Offline request checks against Statsig's published response examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import statsig_node as native
from nodes.core.registry import NodeFactory

TOKEN = "console-synthetic-statsig-fixture"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/statsig/documented_responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="statsig-test", node_type="automation-statsig",
        node_data={"config": config, "credentials": {"credential_type": "statsig_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_published_method_route_and_response(monkeypatch, operation):
    fixture = FIXTURES[operation]
    config = {"operation": operation}
    fields = {"gates": "gate_id", "dynamic_configs": "config_id", "experiments": "experiment_id", "segments": "segment_id", "tags": "tag_id"}
    if "{id}" in fixture["path"]:
        config[fields[fixture["path"].split("/")[3]]] = "selected_id"
    if operation.startswith("create_"):
        config["name"] = "my_resource"
    if operation in {"create_tag", "update_tag"}:
        config["description"] = "my tag description"
    if operation == "update_gate":
        config.update(is_enabled=False, rules=[], tags=[])
    if operation == "update_dynamic_config":
        config.update(default_value={"greeting": "hello"}, is_enabled=False)
    requests = transport(monkeypatch, fixture["response"])
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result.get("data") == fixture["response"].get("data")
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    assert request.url.host == "statsigapi.net"
    assert request.url.path == fixture["path"].replace("{id}", "selected_id")
    assert request.headers["STATSIG-API-KEY"] == TOKEN
    assert request.headers["STATSIG-API-VERSION"] == "20240601"
    assert "authorization" not in request.headers
    assert dict(request.url.params) == ({"limit": "100", "page": "1"} if operation.startswith("list_") else {})
    if operation == "update_gate":
        assert json.loads(request.content) == {"isEnabled": False, "rules": [], "tags": []}
    if operation == "update_dynamic_config":
        assert json.loads(request.content) == {"defaultValue": {"greeting": "hello"}, "isEnabled": False}
    if operation == "create_tag":
        assert json.loads(request.content) == {"name": "my_resource", "description": "my tag description"}
    if request.method in {"GET", "PUT", "DELETE"}:
        assert request.content == b""


@pytest.mark.asyncio
async def test_paging_and_picker_never_follow_next_url(monkeypatch):
    pagination = {"itemsPerPage": 100, "pageNumber": 3, "nextPage": "https://untrusted.example/next", "previousPage": None}
    requests = transport(monkeypatch, {"message": "ok", "data": [{"id": "my_gate", "name": "My Gate"}], "pagination": pagination})
    result = await node({"operation": "list_gates", "page": 3, "limit": 25}).execute({})
    assert result["pagination"] == pagination
    assert dict(requests[0].url.params) == {"limit": "25", "page": "3"}
    options = await native.StatsigNode.load_field_options("gate_id", credential_data={"credential_type": "statsig_api_key", "api_key": TOKEN}, page_token="3", search="my")
    assert options == {"options": [{"value": "my_gate", "label": "My Gate"}], "next_page_token": "4"}
    assert len(requests) == 2 and all(r.url.host == "statsigapi.net" for r in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_errors_do_not_retry_or_leak_key(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={"message": "Invalid key: " + TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "enable_gate", "gate_id": "my_gate"}).execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value)
    assert "Invalid key:" in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>unexpected</html>"), httpx.Response(200, json={"data": None}), httpx.Response(200, json=[]), httpx.Response(200, json={"data": [{}]})])
async def test_invalid_read_is_not_evidence(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "list_gates"}).execute({})


@pytest.mark.asyncio
async def test_project_identity_and_empty_delete_response(monkeypatch):
    transport(monkeypatch, FIXTURES["get_project"]["response"])
    assert (await node({"operation": "get_project"}).execute({}))["data"]["id"] == "company_id"
    transport(monkeypatch, httpx.Response(201))
    assert (await node({"operation": "delete_gate", "gate_id": "my_gate"}).execute({}))["status"] == "success"


@pytest.mark.parametrize("bad", ["../project", "a/b", "a?x=1", "a#b", "a\\b", ".", "..", "a\nb"])
def test_ids_refuse_route_injection(bad):
    with pytest.raises(ValidationError):
        native.GetGate(gate_id=bad)


def test_manual_key_default_type_and_password_field():
    credential = native.StatsigAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "statsig_api_key"
    assert not native.StatsigAPIKeyCredential.model_fields["credential_type"].is_required()
    assert native.StatsigAPIKeyCredential.model_json_schema()["properties"]["api_key"]["ui:widget"] == "password"
    assert TOKEN not in repr(credential)


@pytest.mark.asyncio
async def test_rule_replacement_body(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["update_gate"]["response"])
    rules = [{"name": "CA", "passPercentage": 25, "conditions": [{"type": "country", "operator": "any", "targetValue": ["CA"]}], "environments": ["staging"]}]
    await node({"operation": "update_gate", "gate_id": "my_gate", "rules": rules}).execute({})
    assert json.loads(requests[0].content) == {"rules": rules}
