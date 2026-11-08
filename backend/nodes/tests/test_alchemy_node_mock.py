"""Alchemy Admin API request contract and documented-response regression tests."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import alchemy_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-alchemy-access-key"
APP = json.loads((Path(__file__).parent / "fixtures/alchemy/created_app.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="alchemy-fixture", node_type="automation-alchemy",
        node_data={"config": config, "credentials": {"credential_type": "alchemy_access_key", "access_key": TOKEN}})


def transport(monkeypatch, body=APP, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "list_chains"}, "GET", "/v1/chains", None),
    ({"operation": "list_apps", "limit": 10, "cursor": "a+b /?"}, "GET", "/v1/apps", None),
    ({"operation": "get_app", "app_id": "app_123"}, "GET", "/v1/apps/app_123", None),
    ({"operation": "create_app", "name": "My App", "description": "Example app", "network_allowlist": ["ETH_MAINNET", "ARB_MAINNET"], "products": ["node-api", "webhooks"]}, "POST", "/v1/apps", {"name": "My App", "description": "Example app", "networkAllowlist": ["ETH_MAINNET", "ARB_MAINNET"], "products": ["node-api", "webhooks"]}),
    ({"operation": "update_app", "app_id": "app_123", "name": "Renamed App"}, "PATCH", "/v1/apps/app_123", {"name": "Renamed App"}),
    ({"operation": "delete_app", "app_id": "app_123"}, "DELETE", "/v1/apps/app_123", None),
    ({"operation": "update_network_allowlist", "app_id": "app_123", "network_allowlist": ["ETH_MAINNET"]}, "PUT", "/v1/apps/app_123/networks", {"networkAllowlist": ["ETH_MAINNET"]}),
    ({"operation": "update_address_allowlist", "app_id": "app_123", "address_allowlist": [{"value": "0x0000000000000000000000000000000000000001", "name": "Primary"}]}, "PUT", "/v1/apps/app_123/address-allowlist", {"addressAllowlist": [{"value": "0x0000000000000000000000000000000000000001", "name": "Primary"}]}),
    ({"operation": "update_origin_allowlist", "app_id": "app_123", "origin_allowlist": [{"value": "https://example.com"}]}, "PUT", "/v1/apps/app_123/origin-allowlist", {"originAllowlist": [{"value": "https://example.com"}]}),
    ({"operation": "update_ip_allowlist", "app_id": "app_123", "ip_allowlist": []}, "PUT", "/v1/apps/app_123/ip-allowlist", {"ipAllowlist": []}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES)
async def test_operation_contract_and_documented_app_response(monkeypatch, config, method, path, body):
    reply = APP
    if config["operation"] == "list_chains":
        reply = {"data": [{"id": "ETH_MAINNET", "name": "Ethereum Mainnet"}]}
    elif config["operation"] == "list_apps":
        reply = {"data": {"apps": [APP["data"]], "totalCount": 2, "cursor": "next+page"}}
    elif config["operation"] == "delete_app":
        reply = {"data": {"id": "app_123", "message": "App deleted"}}
    requests = transport(monkeypatch, reply, 201 if method == "POST" else 200)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path
    assert req.url.host == "admin-api.alchemy.com"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(req.content) if req.content else None) == body
    if config["operation"] == "list_apps":
        assert dict(req.url.params) == {"limit": "10", "cursor": "a+b /?"}
        assert result["next_cursor"] == "next+page" and result["has_more"]
    else:
        assert not req.url.params
    assert TOKEN not in str(result)
    assert APP["data"]["apiKey"] not in str(result)
    assert APP["data"]["webhookApiKey"] not in str(result)
    assert "rpcUrl" not in str(result) and "wsUrl" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_http_errors_never_echo_secrets_or_retry_writes(monkeypatch, status):
    requests = transport(monkeypatch, {"error": TOKEN}, status)
    result = await node({"operation": "create_app", "name": "My App", "network_allowlist": []}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"error": "bad"}, {"data": None}, {"data": {"apps": [], "totalCount": "bad"}}, {"data": {"apps": [], "totalCount": 2, "cursor": "same"}}])
async def test_bad_envelopes_and_stalled_pagination_fail(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "list_apps", "cursor": "same"}).execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_empty_account_is_successful_read(monkeypatch):
    transport(monkeypatch, {"data": {"apps": [], "totalCount": 0}})
    result = await node({"operation": "list_apps"}).execute({})
    assert result["items"] == [] and result["next_cursor"] is None and result["has_more"] is False
    assert native.AlchemyNode.connection_evidence.operation == "list_apps"


@pytest.mark.parametrize("app_id", ["..", "a/b", "a?x=y", "a%2Fb", "a\\b", "a b"])
def test_invalid_app_ids(app_id):
    with pytest.raises(ValidationError):
        native.GetApp(app_id=app_id)


@pytest.mark.parametrize("key", ["Bearer abc", "https://example.com/token", "<token>"])
def test_invalid_credentials(key):
    with pytest.raises(ValidationError):
        native.AlchemyAccessKeyCredential(access_key=key)


def test_config_constraints():
    with pytest.raises(ValidationError):
        native.ListApps(limit=26)
    with pytest.raises(ValidationError):
        native.UpdateApp(app_id="app_123")
    with pytest.raises(ValidationError):
        native.CreateApp(name="My App", network_allowlist=[], products=["not-a-product"])


@pytest.mark.asyncio
async def test_provider_auth_rejection_is_preserved_for_connect(monkeypatch):
    transport(monkeypatch, {"error": {"message": "Requires authentication", "status": 401, "code": 401}}, 401)
    result = await node({"operation": "list_apps"}).execute({})
    assert result["status"] == "error" and result["error"] == "Requires authentication"
