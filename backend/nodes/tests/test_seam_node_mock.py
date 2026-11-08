"""Offline Seam route, serialization, response and credential regressions."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import seam_node as seam
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "seam_test_synthetic_no_account"
ID = "3c90c3cc-0d44-4b50-8888-8dd25736052a"
CREDS = {"credential_type": "seam_api_key", "api_key": TOKEN}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, creds=None):
    return NodeFactory.create_node(node_id="seam-test", node_type="automation-seam", node_data={"config": config, "credentials": CREDS if creds is None else creds})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(seam, "guarded_async_client", client)
    return requests


CASES = [
    ("get_workspace", "GET", "/workspaces/get", {}, {"workspace": {"workspace_id": ID, "name": "Sandbox"}}),
    ("list_devices", "GET", "/devices/list", {"limit": 10, "page_cursor": "next+page &", "search": "Front + Café"}, {"devices": [], "pagination": {"next_page_cursor": "cursor-2"}}),
    ("get_device", "GET", "/devices/get", {"device_id": ID}, {"device": {"device_id": ID}}),
    ("update_device", "PATCH", "/devices/update", {"device_id": ID, "name": "Front door"}, {}),
    ("list_locks", "GET", "/locks/list", {"connected_account_id": ID}, {"locks": [], "devices": []}),
    ("get_lock", "GET", "/locks/get", {"device_id": ID}, {"lock": {"device_id": ID}, "device": {"device_id": ID}}),
    ("lock_door", "POST", "/locks/lock_door", {"device_id": ID}, {"action_attempt": {"action_attempt_id": ID, "status": "pending"}}),
    ("unlock_door", "POST", "/locks/unlock_door", {"device_id": ID}, {"action_attempt": {"action_attempt_id": ID, "status": "pending"}}),
    ("list_access_codes", "GET", "/access_codes/list", {"device_id": ID, "limit": 5, "page_cursor": "cursor-1"}, {"access_codes": [], "pagination": {"next_page_cursor": None}}),
    ("get_access_code", "GET", "/access_codes/get", {"access_code_id": ID}, {"access_code": {"access_code_id": ID, "code": "1234"}}),
    ("create_access_code", "POST", "/access_codes/create", {"device_id": ID, "name": "Guest", "code": "012345", "starts_at": "2030-01-01T00:00:00Z", "ends_at": "2030-01-02T00:00:00Z"}, {"access_code": {"access_code_id": ID}, "action_attempt": {"status": "pending"}}),
    ("update_access_code", "PATCH", "/access_codes/update", {"access_code_id": ID, "name": "New guest"}, {"action_attempt": {"status": "pending"}}),
    ("delete_access_code", "DELETE", "/access_codes/delete", {"access_code_id": ID}, {"action_attempt": {"status": "pending"}}),
    ("list_connected_accounts", "GET", "/connected_accounts/list", {"search": "guest@example.com", "limit": 5, "page_cursor": "cursor"}, {"connected_accounts": [], "pagination": {"next_page_cursor": None}}),
    ("get_connected_account", "GET", "/connected_accounts/get", {"connected_account_id": ID}, {"connected_account": {"connected_account_id": ID}}),
    ("sync_connected_account", "POST", "/connected_accounts/sync", {"connected_account_id": ID}, {}),
    ("get_action_attempt", "GET", "/action_attempts/get", {"action_attempt_id": ID}, {"action_attempt": {"action_attempt_id": ID, "status": "success"}}),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,values,body", CASES)
async def test_seam_exact_single_request(monkeypatch, operation, method, path, values, body):
    requests = transport(monkeypatch, {"ok": True, **body})
    result = await node({"operation": operation, **values}).execute({})
    assert result == {"status": "success", "ok": True, **body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "connect.getseam.com" and request.url.scheme == "https"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if method in {"GET", "DELETE"}:
        assert dict(request.url.params) == {k: str(v) for k, v in values.items()}
        assert not request.content
    else:
        assert json.loads(request.content) == values
    assert TOKEN not in str(result)

@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401,{"ok":False,"error":{"message":"Invalid API key"}}), (200,{"ok":False,"error":{"message":"Device unavailable"}}), (302,{"ok":True})])
async def test_seam_rejection_never_success_or_retried(monkeypatch, status, body):
    requests = transport(monkeypatch, body, status)
    result = await node({"operation":"unlock_door","device_id":ID}).execute({})
    assert result["status"] == "error" and len(requests) == 1
    if "error" in body: assert result["error"] == body["error"]["message"]

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"ok":True}, {"ok":True,"workspace":[]}, {"ok":True,"workspace":{}}, {"ok":True,"workspace":{"workspace_id":ID}}, {"ok":True,"workspace":{"workspace_id":"invalid","name":"Sandbox"}}])
async def test_seam_missing_workspace_cannot_prove_account(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation":"get_workspace"}).execute({})

@pytest.mark.parametrize("config", [
    {"operation":"get_device","device_id":"not-an-id"},
    {"operation":"update_access_code","access_code_id":ID},
    {"operation":"create_access_code","device_id":ID,"code":"1x34"},
    {"operation":"create_access_code","device_id":ID,"starts_at":"2030-01-01"},
    {"operation":"create_access_code","device_id":ID,"starts_at":"2030-01-02T00:00:00Z","ends_at":"2030-01-01T00:00:00Z"},
    {"operation":"get_workspace","url":"https://attacker.test"},
])
def test_seam_rejects_invalid_input(config):
    with pytest.raises(ValueError): node(config)

@pytest.mark.parametrize("key", ["https://console.seam.co", "<token>", "Bearer example", "two words"])
def test_seam_bad_key(key):
    with pytest.raises(ValidationError): seam.SeamAPIKeyCredential(api_key=key)


def test_seam_discovery_and_connection_contract():
    assert NODE_REGISTRY["automation-seam"] is seam.SeamNode
    assert len(seam.ROUTES) == 17
    assert seam.SeamAPIKeyCredential(api_key="  " + TOKEN + "\n").api_key == TOKEN
    evidence = seam.SeamNode.connection_evidence
    assert evidence.identity_operation == "get_workspace"
    assert seam.ROUTES[evidence.identity_operation][:2] == ("GET", "/workspaces/get")


@pytest.mark.asyncio
async def test_seam_connection_shows_workspace_name(monkeypatch):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, {"ok": True, "workspace": {"workspace_id": ID, "name": "My Sandbox Workspace"}})
    async def run(**kwargs):
        assert kwargs["operation"] == "get_workspace"
        assert kwargs["credential_data"] == CREDS
        return await node({"operation": kwargs["operation"]}).execute({})
    monkeypatch.setattr(run_op, "run_node_operation", run)
    evidence = await collect_evidence(node_type="automation-seam", user_id="seam-fixture", credential_data=CREDS)
    assert evidence.reachable is True and evidence.account_label == "My Sandbox Workspace"
    assert len(requests) == 1
