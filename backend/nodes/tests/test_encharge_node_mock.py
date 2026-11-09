"""Native factory and HTTP contract tests; no live Encharge account is used."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import encharge_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

KEY = "synthetic-encharge-key-42"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config, creds=None):
    return NodeFactory.create_node(node_id="encharge-fixture", node_type="automation-encharge", node_data={"config": config, "credentials": creds or {"credential_type": "encharge_api_key", "api_key": KEY}})

def transport(monkeypatch, status, payload=None, text=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, text=text) if text is not None else httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests

CASES = [
    ({"operation": "get_people", "people": [{"email": "slav@encharge.io"}, {"userId": "abc"}]}, "GET", "/people", 200, {"users": [{"email": "slav@encharge.io"}]}, None),
    ({"operation": "upsert_people", "people": [{"email": "slav@encharge.io", "firstName": "Slav", "custom": 42}]}, "POST", "/people", 200, {"users": []}, [{"email": "slav@encharge.io", "firstName": "Slav", "custom": 42}]),
    ({"operation": "archive_people", "people": [{"userId": "abc"}]}, "DELETE", "/people", 204, None, None),
    ({"operation": "get_account"}, "GET", "/accounts/info", 200, {"accountId": 7, "name": "Example", "status": "active"}, None),
    ({"operation": "list_fields"}, "GET", "/fields", 200, {"items": []}, None),
    ({"operation": "create_fields", "fields": [{"name": "plan", "type": "string"}]}, "POST", "/fields", 200, {"items": []}, [{"name": "plan", "type": "string", "readOnly": False, "array": False}]),
    ({"operation": "update_field", "field_name": "plan", "field": {"name": "plan", "type": "string", "title": "Plan"}}, "PATCH", "/fields/plan", 200, {"field": {"name": "plan"}}, {"name": "plan", "type": "string", "title": "Plan", "readOnly": False, "array": False}),
    ({"operation": "delete_field", "field_name": "plan"}, "DELETE", "/fields/plan", 204, None, None),
    ({"operation": "list_segments"}, "GET", "/segments", 200, {"segments": [{"id": 1, "name": "Trial users"}]}, None),
    ({"operation": "list_segment_people", "segment_id": 12, "limit": 1, "offset": 4, "attributes": "email,firstName", "sort": "email", "order": "desc"}, "GET", "/segments/12/people", 200, {"people": [{"email": "slav@encharge.io"}]}, None),
    ({"operation": "add_tags", "email": "slav@encharge.io", "tag": "tag1,tag2"}, "POST", "/tags", 201, None, {"email": "slav@encharge.io", "tag": "tag1,tag2"}),
    ({"operation": "remove_tags", "userId": "abc", "tag": "tag1"}, "DELETE", "/tags", 204, None, {"userId": "abc", "tag": "tag1"}),
    ({"operation": "unsubscribe_person", "email": "slav@encharge.io"}, "POST", "/people/unsubscribe", 204, None, None),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,status,payload,body", CASES)
async def test_wire_contract(monkeypatch, config, method, path, status, payload, body):
    requests = transport(monkeypatch, status, payload)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["http_status"] == status
    assert KEY not in str(result) and len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == "/v1" + path and req.url.host == "api.encharge.io"
    assert req.headers["X-Encharge-Token"] == KEY and "authorization" not in req.headers
    assert (json.loads(req.content) if req.content else None) == body
    if config["operation"] == "get_people":
        assert dict(req.url.params) == {"people[0][email]": "slav@encharge.io", "people[1][userId]": "abc"}
    if config["operation"] == "archive_people":
        assert dict(req.url.params) == {"people[0][userId]": "abc", "force": "false"}
    if config["operation"] == "unsubscribe_person":
        assert dict(req.url.params) == {"email": "slav@encharge.io"}
    if config["operation"] == "get_account":
        assert result["data"]["status"] == "active"
    if config["operation"] == "list_segment_people":
        assert req.url.params.get_list("attributes") == ["email", "firstName"]
        assert req.url.params["limit"] == "1" and req.url.params["offset"] == "4"
        assert result["next_offset"] == 5

@pytest.mark.asyncio
async def test_json_editor_and_explicit_permanent_removal(monkeypatch):
    requests = transport(monkeypatch, 204)
    result = await node({"operation": "archive_people", "people": '[{"userId":"abc"}]', "force": True}).execute({})
    assert result["acknowledged"] and requests[0].url.params["force"] == "true"

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_provider_error_and_secret_redaction(monkeypatch, status):
    requests = transport(monkeypatch, status, {"error": {"message": "Rejected key " + KEY}})
    result = await node({"operation": "list_segments"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected key [redacted]"}
    assert len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"segments": {}}, {"error": "denied"}, []])
async def test_bad_response(monkeypatch, payload):
    transport(monkeypatch, 200, payload)
    assert (await node({"operation": "list_segments"}).execute({}))["status"] == "error"

@pytest.mark.asyncio
async def test_html_and_secret_echoes(monkeypatch):
    transport(monkeypatch, 200, text="<html>Sign in</html>")
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"
    transport(monkeypatch, 200, {"segments": [{"name": KEY, "id": 1}]})
    assert KEY not in str(await node({"operation": "list_segments"}).execute({}))

@pytest.mark.asyncio
async def test_terminal_page(monkeypatch):
    transport(monkeypatch, 200, {"people": []})
    result = await node({"operation": "list_segment_people", "segment_id": 1}).execute({})
    assert result["next_offset"] is None

@pytest.mark.parametrize("config", [
    {"operation": "get_people", "people": []}, {"operation": "get_people", "people": [{}]},
    {"operation": "upsert_people", "people": "not-json"},
    {"operation": "add_tags", "tag": "trial"}, {"operation": "unsubscribe_person"},
    {"operation": "update_field", "field_name": "plan", "field": {"name": "other", "type": "string"}},
    {"operation": "delete_field", "field_name": ".."}, {"operation": "list_segment_people", "segment_id": 0},
])
def test_invalid_inputs(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)

def test_registration_manual_credential_and_fixture():
    assert NODE_REGISTRY["automation-encharge"] is native.EnchargeNode
    assert native.EnchargeAPIKeyCredential.model_validate({"api_key": KEY}).credential_type == "encharge_api_key"
    fixture = json.loads((Path(__file__).parent / "fixtures/encharge/contract.json").read_text())
    assert set(fixture["operations"]) == set(native.ROUTES) and len(native.ROUTES) == 13
    for name, op in fixture["operations"].items():
        assert native.ROUTES[name][:3] == (op["method"], op["path"], op["success_status"])
    assert native.EnchargeNode.connection_evidence.operation == "list_segments"
