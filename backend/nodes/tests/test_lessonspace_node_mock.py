"""Lessonspace request, authentication, response and failure boundary tests."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import lessonspace_node as native
from nodes.core.registry import NodeFactory

TOKEN = "lessonspace-test-key"
CASES = json.loads((Path(__file__).parent / "fixtures/lessonspace/requests.json").read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="lessonspace-test", node_type="automation-lessonspace",
        node_data={"config": config, "credentials": {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}})


def transport(monkeypatch, body=None, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config", CASES, ids=lambda c: c["operation"])
async def test_operations_exact_routes_auth_query_and_body(monkeypatch, config):
    op = config["operation"]
    method, route = native.ROUTES[op]
    for name in ("session", "space", "user"):
        if "{" + name + "}" in route:
            route = route.replace("{" + name + "}", str(config["user_id" if name == "user" else name]))
    status = 204 if op == "delete_user" else 201 if op == "launch_space" else 200
    body = {"count": 1, "next": None, "previous": None, "results": [{"id": 42, "name": "Teacher"}]} if op.startswith("list_") else {"name": "Algebra", "secret": "unrestricted-space-key", "api_key": TOKEN}
    requests = transport(monkeypatch, body, status)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["http_status"] == status
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/v2" + route
    assert request.url.host == "api.thelessonspace.com" and request.url.scheme == "https"
    assert request.headers["Authorization"] == "Organisation " + TOKEN
    assert "unrestricted-space-key" not in str(result) and TOKEN not in str(result)
    values = {k: v for k, v in config.items() if k != "operation"}
    if method == "GET":
        values = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in values.items() if k not in {"session", "space"}}
        assert dict(request.url.params) == values
    elif method in {"POST", "PATCH"}:
        if op == "update_session": values.pop("session")
        assert json.loads(request.content) == values
    else:
        assert not request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("status,state", [(200,"available"),(202,"pending"),(204,"disabled")])
async def test_recording_states_are_distinct_and_links_are_not_fetched(monkeypatch, status, state):
    requests = transport(monkeypatch, {"url": "https://recording.example.test/signed"}, status)
    result = await node(CASES[4]).execute({})
    assert result["status"] == "success" and result["recording_state"] == state and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500, 503])
async def test_errors_are_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"detail": "Rejected " + TOKEN}, status)
    result = await node(CASES[10]).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, [], {}, {"count":1,"results":{}}, {"detail":"not allowed"}])
async def test_malformed_evidence_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation":"list_users"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_network_failure_is_sanitized(monkeypatch):
    def client(**kwargs):
        def respond(request): raise httpx.ReadTimeout(TOKEN, request=request)
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node(CASES[2]).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.parametrize("config", [{"operation":"get_session","session":"../foreign"}, {"operation":"delete_user","user_id":True}, {"operation":"list_users","page":0}, {"operation":"launch_space","id":""}, {"operation":"update_session","session":"12345678-1234-4234-8234-123456789abc"}, {"operation":"custom_request"}])
def test_config_rejects_invalid_ids_missing_fields_and_unknown_operations(config):
    with pytest.raises(ValueError): node(config)


def test_credential_manual_default_and_evidence_contract():
    credential = native.LessonspaceAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == native.CREDENTIAL_TYPE and credential.api_key == TOKEN
    assert native.LessonspaceNode.connection_evidence.operation == "list_users"
    for value in ["Organisation " + TOKEN, "https://example.test/key", "key\r\nInjected: header"]:
        with pytest.raises(ValidationError): native.LessonspaceAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_long_key_is_redacted_before_error_truncation(monkeypatch):
    key = "sensitive-" + "x" * 3000
    transport(monkeypatch, {"detail": "Rejected " + key}, 403)
    instance = NodeFactory.create_node(node_id="lessonspace-long-key", node_type="automation-lessonspace",
        node_data={"config": {"operation": "list_users"}, "credentials": {"api_key": key}})
    result = await instance.execute({})
    assert result["message"] == "Rejected [redacted]"
