"""Exercise Orgo through the factory and captured HTTP; no live credentials."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import orgo_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-orgo-key-42"
ID = "6f1c2a7e-3b9d-4c1a-9e2f-0a1b2c3d4e5f"
CREDENTIAL = {"credential_type": "orgo_api_key", "api_key": KEY}
CONTRACT = json.loads((Path(__file__).parent / "fixtures/orgo/contract.json").read_text())["operations"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="orgo-fixture", node_type="automation-orgo",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body=None, status=200, *, raw=None, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, **({"content": raw} if raw is not None else {"json": body}), headers=headers)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    {"operation": "get_me"},
    {"operation": "get_account_capacity"},
    {"operation": "get_account_limits"},
    {"operation": "list_workspaces"},
    {"operation": "create_computer", "workspace_id": ID, "name": "agent-1", "os": "linux", "ram": 8},
    {"operation": "get_computer", "computer_id": ID},
    {"operation": "update_computer", "computer_id": ID, "ends_in_hours": 4},
    {"operation": "delete_computer", "computer_id": ID},
    {"operation": "start_computer", "computer_id": ID, "ends_in_hours": 4},
    {"operation": "stop_computer", "computer_id": ID},
    {"operation": "restart_computer", "computer_id": ID},
    {"operation": "suspend_computer", "computer_id": ID},
    {"operation": "resume_computer", "computer_id": ID, "ends_in_hours": 4},
    {"operation": "get_computer_operation", "computer_id": ID, "operation_id": ID},
    {"operation": "run_bash", "computer_id": ID, "command": "uname -a", "timeout": 30, "screen": "0"},
    {"operation": "click", "computer_id": ID, "x": 640, "y": 400, "button": "left", "double": False},
    {"operation": "type_text", "computer_id": ID, "text": "hello"},
    {"operation": "press_key", "computer_id": ID, "key": "ctrl+c"},
    {"operation": "list_public_urls", "computer_id": ID},
    {"operation": "create_public_url", "computer_id": ID, "port": 3000, "name": "cool-thing"},
    {"operation": "update_public_url", "computer_id": ID, "url_id": ID, "port": 8000},
    {"operation": "delete_public_url", "computer_id": ID, "url_id": ID},
    {"operation": "list_computer_apps", "computer_id": ID},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config", CASES, ids=lambda c: c["operation"])
async def test_orgo_pinned_routes_and_request_examples(monkeypatch, config):
    operation = config["operation"]
    contract = CONTRACT[operation]
    responses = contract["contract"]["responses"]
    status = min(int(code) for code in responses if code.isdigit() and code.startswith("2"))
    payload = None if status == 204 else {"id": ID, "name": "agent-1", "operation_id": ID, "status": "running"}
    requests = transport(monkeypatch, payload, status)
    output = await node(config).execute({})
    assert output == {"status": "success", "http_status": status, "data": payload}
    assert len(requests) == 1
    request = requests[0]
    path = contract["path"].replace("{id}", ID).replace("{operationId}", ID).replace("{urlId}", ID)
    assert request.method == contract["method"] and request.url.path == path
    assert request.url.host == "www.orgo.ai"
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert KEY not in str(output)
    if request.method in {"GET", "DELETE"}:
        assert not request.content
    else:
        body = json.loads(request.content)
        assert not {"operation", "computer_id", "url_id", "screen", "run_async", "keep_forever"} & body.keys()
        example = contract["contract"].get("requestBody", {}).get("content", {}).get("application/json", {}).get("example")
        if example:
            assert all(body.get(key) == value for key, value in example.items())
    if operation == "run_bash":
        assert request.url.params["screen"] == "0"
    if operation in {"start_computer", "stop_computer"}:
        assert json.loads(request.content)["async"] is True


@pytest.mark.asyncio
async def test_orgo_end_and_password_nulls(monkeypatch):
    requests = transport(monkeypatch, {})
    await node({"operation": "update_computer", "computer_id": ID, "keep_forever": True}).execute({})
    assert json.loads(requests[-1].content) == {"ends_at": None}
    await node({"operation": "update_public_url", "computer_id": ID, "url_id": ID, "remove_password": True}).execute({})
    assert json.loads(requests[-1].content) == {"password": None}
    for config in [
        {"operation": "update_computer", "computer_id": ID},
        {"operation": "update_public_url", "computer_id": ID, "url_id": ID},
        {"operation": "update_public_url", "computer_id": ID, "url_id": ID, "password": "secret", "remove_password": True},
    ]:
        with pytest.raises(ValueError):
            await node(config).execute({})
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_orgo_creation_idempotency_and_lifecycle_polling(monkeypatch):
    requests = transport(monkeypatch, {"id": ID}, 201)
    await node({"operation": "create_computer", "workspace_id": ID, "name": "agent-1", "idempotency_key": "job-42", "compute_request_id": ID}).execute({})
    assert requests[0].headers["Idempotency-Key"] == "job-42"
    assert "idempotency_key" not in json.loads(requests[0].content)
    assert json.loads(requests[0].content)["compute_request_id"] == ID
    payload = {"id": ID, "status": "stopping", "operation_id": ID, "poll_url": f"/api/computers/{ID}/operations/{ID}"}
    requests = transport(monkeypatch, payload, 202)
    output = await node({"operation": "stop_computer", "computer_id": ID}).execute({})
    assert output["http_status"] == 202 and output["data"] == payload and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_orgo_provider_rejections_are_preserved_and_not_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Rejected " + KEY, "code": "denied", "request_id": "req-1"}, status, headers={"Retry-After": "2"})
    output = await node({"operation": "delete_computer", "computer_id": ID}).execute({})
    assert output["status"] == "error" and output["http_status"] == status
    assert output["message"] == "Rejected [redacted]"
    assert output["data"]["request_id"] == "req-1" and output["retry_after"] == "2"
    assert KEY not in str(output) and len(requests) == 1


@pytest.mark.asyncio
async def test_orgo_arrays_empty_responses_and_invalid_json(monkeypatch):
    payload = [{"id": ID, "name": "Work"}]
    transport(monkeypatch, payload)
    assert (await node({"operation": "list_workspaces"}).execute({}))["data"] == payload
    transport(monkeypatch, None, 204)
    assert (await node({"operation": "delete_computer", "computer_id": ID}).execute({}))["data"] is None
    transport(monkeypatch, raw=b"<html>Bad gateway</html>")
    assert (await node({"operation": "get_me"}).execute({}))["status"] == "error"
    transport(monkeypatch, {"nested": [KEY]})
    assert (await node({"operation": "get_me"}).execute({}))["data"] == {"nested": ["[redacted]"]}


def test_orgo_manual_connect_and_config_validation():
    assert native.OrgoAPIKeyCredential(api_key=KEY).credential_type == "orgo_api_key"
    assert native.OrgoAPIKeyCredential(api_key="\r\n" + KEY + "\n").api_key == KEY
    for key in ["Bearer " + KEY, "https://www.orgo.ai", "bad\rinjected"]:
        with pytest.raises(ValidationError):
            native.OrgoAPIKeyCredential(api_key=key)
    for identifier in ["..", "a/b", "a?key=value", "a#fragment", "%2e%2e"]:
        with pytest.raises(ValidationError):
            native.OrgoGetComputerConfig(computer_id=identifier)
    for config in [
        lambda: native.OrgoCreateComputerConfig(workspace_id=ID, name="agent-1", ram=3),
        lambda: native.OrgoRunBashConfig(computer_id=ID, command="uname -a", timeout=301),
        lambda: native.OrgoStartComputerConfig(computer_id=ID, ends_in_hours=4, keep_forever=True),
        lambda: native.OrgoCreatePublicUrlConfig(computer_id=ID, port=65536),
        lambda: native.OrgoGetComputerOperationConfig(computer_id=ID, operation_id="not-a-uuid"),
    ]:
        with pytest.raises(ValidationError):
            config()
    assert native.OrgoNode.connection_evidence.identity_operation == "get_me"
    assert CONTRACT.keys() == native.ROUTES.keys() == {case["operation"] for case in CASES}


DOCUMENTED = json.loads((Path(__file__).parent / "fixtures/orgo/documented_responses.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [c for c in CASES if CONTRACT[c["operation"]]["method"] + " " + CONTRACT[c["operation"]]["path"] in DOCUMENTED], ids=lambda c: c["operation"])
async def test_orgo_documented_response_parsing(monkeypatch, config):
    contract = CONTRACT[config["operation"]]
    witness = DOCUMENTED[contract["method"] + " " + contract["path"]]
    requests = transport(monkeypatch, witness["body"])
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == witness["body"]
    assert witness["source"].startswith("https://docs.orgo.ai/") and len(requests) == 1


@pytest.mark.asyncio
async def test_orgo_action_failure_envelopes(monkeypatch):
    requests = transport(monkeypatch, {"success": False, "error": "Application rejected the action"})
    output = await node({"operation": "press_key", "computer_id": ID, "key": "ctrl+c"}).execute({})
    assert output["status"] == "error" and output["message"] == "Application rejected the action"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_orgo_connection_evidence_uses_account_read(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, {"user": {"id": ID, "email": "person@example.com"}})
    evidence = await collect_evidence(node_type="automation-orgo", user_id=ID, credential_data=CREDENTIAL)
    assert evidence.reachable is True and evidence.account_label == "person@example.com"
    assert len(requests) == 1 and requests[0].method == "GET" and requests[0].url.path == "/api/me"
