"""Felt v2 requests through the production node factory; no account required."""
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import felt_node as native
from nodes.core.registry import NodeFactory

TOKEN = "felt_pat_synthetic_secret"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="felt-test", node_type="automation-felt", node_data={
        "config": config, "credentials": {"credential_type": "felt_api_token", "api_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def handler(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_current_user"}, "GET", "/user", None),
    ({"operation": "list_projects", "workspace_id": "workspace123"}, "GET", "/projects", None),
    ({"operation": "create_project", "name": "Research", "visibility": "private"}, "POST", "/projects", {"name": "Research", "visibility": "private"}),
    ({"operation": "get_project", "project_id": "project123"}, "GET", "/projects/project123", None),
    ({"operation": "update_project", "project_id": "project123", "name": "Updated"}, "POST", "/projects/project123/update", {"name": "Updated"}),
    ({"operation": "delete_project", "project_id": "project123"}, "DELETE", "/projects/project123", None),
    ({"operation": "create_map", "title": "Sites", "lat": 40, "lon": -3}, "POST", "/maps", {"title": "Sites", "public_access": "private", "lat": 40.0, "lon": -3.0}),
    ({"operation": "get_map", "map_id": "map123"}, "GET", "/maps/map123", None),
    ({"operation": "update_map", "map_id": "map123", "title": "Updated"}, "POST", "/maps/map123/update", {"title": "Updated"}),
    ({"operation": "delete_map", "map_id": "map123"}, "DELETE", "/maps/map123", None),
    ({"operation": "duplicate_map", "map_id": "map123", "title": "Copy"}, "POST", "/maps/map123/duplicate", {"title": "Copy"}),
    ({"operation": "move_map", "map_id": "map123", "project_id": "project123"}, "POST", "/maps/map123/move", {"project_id": "project123"}),
    ({"operation": "list_map_layers", "map_id": "map123", "include_uploading": False}, "GET", "/maps/map123/layers", None),
    ({"operation": "get_map_layer", "map_id": "map123", "layer_id": "layer123"}, "GET", "/maps/map123/layers/layer123", None),
    ({"operation": "delete_map_layer", "map_id": "map123", "layer_id": "layer123"}, "DELETE", "/maps/map123/layers/layer123", None),
    ({"operation": "refresh_map_layer", "map_id": "map123", "layer_id": "layer123"}, "POST", "/maps/map123/layers/layer123/refresh", None),
    ({"operation": "list_map_elements", "map_id": "map123"}, "GET", "/maps/map123/elements", None),
    ({"operation": "delete_map_element", "map_id": "map123", "element_id": "element123"}, "DELETE", "/maps/map123/elements/element123", None),
    ({"operation": "list_map_layer_groups", "map_id": "map123"}, "GET", "/maps/map123/layer_groups", None),
    ({"operation": "get_map_layer_group", "map_id": "map123", "layer_group_id": "group123"}, "GET", "/maps/map123/layer_groups/group123", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES)
async def test_exact_requests(monkeypatch, config, method, path, body):
    payload = [{"id": "project123", "name": "Research"}] if config["operation"] == "list_projects" else {"id": "map123", "name": "Research"}
    requests = transport(monkeypatch, httpx.Response(204) if method == "DELETE" else httpx.Response(200, json=payload))
    result = await node(config).run({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v2" + path
    assert request.url.scheme == "https" and request.url.host == "felt.com"
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    if config["operation"] == "list_projects":
        assert dict(request.url.params) == {"workspace_id": "workspace123"}
    elif config["operation"] in {"list_map_layers", "list_map_layer_groups"}:
        assert dict(request.url.params) == {"include_uploading": str(config.get("include_uploading", True)).lower()}
    else:
        assert not request.url.query
    if method == "DELETE":
        assert result["acknowledged"] and result["http_status"] == 204
    else:
        assert result["data"] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 404, 429, 500, 302])
async def test_rejection_redacts_secret(monkeypatch, code):
    requests = transport(monkeypatch, httpx.Response(code, text="Token rejected " + TOKEN))
    result = await node({"operation": "get_current_user"}).run({})
    assert result["status"] == "error" and result["http_status"] == code
    assert "Token rejected" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"errors": [{"detail": "denied"}]}, {"error": "denied"}])
async def test_error_envelope(monkeypatch, payload):
    transport(monkeypatch, httpx.Response(200, json=payload))
    result = await node({"operation": "get_current_user"}).run({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_account_identity(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"id": "user123", "name": "Test Account", "email": "test@example.test"}))
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["data"]["name"] == "Test Account"
    assert native.FeltNode.connection_evidence.identity_operation == "get_current_user"


@pytest.mark.parametrize("value", ["../bad", "id/path", "id?x=1", "https://evil.test", "id#frag", "id\nheader"])
def test_resource_path_injection(value):
    with pytest.raises(ValidationError):
        native.FeltGetMapConfig(map_id=value)


@pytest.mark.parametrize("value", ["Bearer secret", "token\nheader", "https://evil.test/token"])
def test_credential_input(value):
    with pytest.raises(ValidationError):
        native.FeltAPITokenCredential(api_token=value)


def test_manual_type_default():
    assert native.FeltAPITokenCredential(api_token=TOKEN).credential_type == "felt_api_token"
