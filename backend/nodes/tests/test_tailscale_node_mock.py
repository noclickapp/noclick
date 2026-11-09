"""Tailscale native factory tests; all HTTP is mocked, no provider sign-in."""
import json

import httpx
import pytest

from nodes import tailscale_node as native
from nodes.core.registry import NodeFactory

TOKEN = "tskey-api-synthetic-test-only"
DEVICE = "n292kg92CNTRL"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="tailscale-test", node_type="automation-tailscale",
        node_data={"config": config, "credentials": credentials or {"credential_type": native.FAMILY, "api_token": TOKEN}})


def transport(monkeypatch, body=None, status=200, raw=None):
    seen = []
    def reply(request):
        seen.append(request)
        return httpx.Response(status, content=raw) if raw is not None else httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return seen


# Expected requests are pinned independently to the published v2 contract.
CASES = [
    ({"operation": "list_devices", "tailnet": "example.com", "fields": "all"}, "GET", "/tailnet/example.com/devices", {"fields": "all"}, None, {"devices": [{"nodeId": DEVICE, "name": "pangolin.tailfe8c.ts.net"}]}),
    ({"operation": "get_device", "device_id": DEVICE}, "GET", f"/device/{DEVICE}", {"fields": "default"}, None, {"nodeId": DEVICE}),
    ({"operation": "delete_device", "device_id": DEVICE}, "DELETE", f"/device/{DEVICE}", {}, None, None),
    ({"operation": "expire_device_key", "device_id": DEVICE}, "POST", f"/device/{DEVICE}/expire", {}, None, None),
    ({"operation": "list_device_routes", "device_id": DEVICE}, "GET", f"/device/{DEVICE}/routes", {}, None, {"advertisedRoutes": ["10.0.0.0/16"], "enabledRoutes": []}),
    ({"operation": "set_device_routes", "device_id": DEVICE, "routes": ["10.0.0.0/16"]}, "POST", f"/device/{DEVICE}/routes", {}, {"routes": ["10.0.0.0/16"]}, {"enabledRoutes": ["10.0.0.0/16"]}),
    ({"operation": "authorize_device", "device_id": DEVICE, "authorized": False}, "POST", f"/device/{DEVICE}/authorized", {}, {"authorized": False}, None),
    ({"operation": "set_device_name", "device_id": DEVICE, "name": "dev-server"}, "POST", f"/device/{DEVICE}/name", {}, {"name": "dev-server"}, None),
    ({"operation": "set_device_tags", "device_id": DEVICE, "tags": []}, "POST", f"/device/{DEVICE}/tags", {}, {"tags": []}, None),
    ({"operation": "update_device_key", "device_id": DEVICE, "key_expiry_disabled": False}, "POST", f"/device/{DEVICE}/key", {}, {"keyExpiryDisabled": False}, None),
    ({"operation": "list_dns_nameservers"}, "GET", "/tailnet/-/dns/nameservers", {}, None, {"dns": ["8.8.8.8"]}),
    ({"operation": "set_dns_nameservers", "dns": []}, "POST", "/tailnet/-/dns/nameservers", {}, {"dns": []}, {"dns": [], "magicDNS": True}),
    ({"operation": "get_dns_preferences"}, "GET", "/tailnet/-/dns/preferences", {}, None, {"magicDNS": True}),
    ({"operation": "set_dns_preferences", "magic_dns": False}, "POST", "/tailnet/-/dns/preferences", {}, {"magicDNS": False}, {"magicDNS": False}),
    ({"operation": "list_dns_search_paths"}, "GET", "/tailnet/-/dns/searchpaths", {}, None, {"searchPaths": ["user1.example.com"]}),
    ({"operation": "set_dns_search_paths", "search_paths": []}, "POST", "/tailnet/-/dns/searchpaths", {}, {"searchPaths": []}, {"searchPaths": []}),
    ({"operation": "list_keys", "all_keys": True}, "GET", "/tailnet/-/keys", {"all": "true"}, None, {"keys": [{"id": "k123456CNTRL", "keyType": "auth"}]}),
    ({"operation": "get_key", "key_id": "k123456CNTRL"}, "GET", "/tailnet/-/keys/k123456CNTRL", {}, None, {"id": "k123456CNTRL"}),
    ({"operation": "delete_key", "key_id": "k123456CNTRL"}, "DELETE", "/tailnet/-/keys/k123456CNTRL", {}, None, None),
    ({"operation": "list_users", "user_type": "shared", "role": "auditor"}, "GET", "/tailnet/-/users", {"type": "shared", "role": "auditor"}, None, {"users": [{"id": "123456", "displayName": "Some User"}]}),
    ({"operation": "get_user", "user_id": "123456"}, "GET", "/users/123456", {}, None, {"id": "123456"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body,response", CASES, ids=[v[0]["operation"] for v in CASES])
async def test_published_wire_contract(monkeypatch, config, method, path, query, body, response):
    seen = transport(monkeypatch, response, raw=b"" if response is None else None)
    output = await node(config).execute({})
    assert output["status"] == "success"
    assert len(seen) == 1  # Neither pagination nor hidden verification calls.
    req = seen[0]
    assert req.method == method and req.url.host == "api.tailscale.com"
    assert req.url.path == "/api/v2" + path and dict(req.url.params) == query
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(req.content) if req.content else None) == body
    assert TOKEN not in str(output)
    if method != "GET":
        assert output["acknowledged"] and output["state_verified"] is False


@pytest.mark.asyncio
async def test_default_tailnet_evidence_and_empty_list(monkeypatch):
    seen = transport(monkeypatch, {"devices": []})
    result = await node({"operation": "list_devices"}).execute({})
    assert result["items"] == [] and result["complete"]
    assert seen[0].url.path == "/api/v2/tailnet/-/devices"
    assert native.TailscaleNode.connection_evidence.proves == "account"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_failures_keep_provider_message_and_redact_token(monkeypatch, status):
    seen = transport(monkeypatch, {"message": "Access denied: " + TOKEN}, status=status)
    result = await node({"operation": "list_devices"}).execute({})
    assert len(seen) == 1 and result["status"] == "error"
    assert result["http_status"] == status
    assert result["error"] == "Access denied: [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"devices": None}, {"devices": [None]}, {"error": "bad"}, {"message": "bad"}])
async def test_invalid_list_never_passes_connection_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "list_devices"}).execute({})
    assert result["status"] == "error" and "items" not in result


@pytest.mark.asyncio
async def test_no_json_and_secret_key_material(monkeypatch):
    transport(monkeypatch, raw=b"<html>login</html>")
    assert (await node({"operation": "get_user", "user_id": "123456"}).execute({}))["status"] == "error"
    transport(monkeypatch, {"keys": [{"id": "k123456CNTRL", "key": "tskey-auth-secret", "description": TOKEN}]})
    result = await node({"operation": "list_keys"}).execute({})
    assert "tskey-auth-secret" not in str(result) and TOKEN not in str(result)
    assert result["items"][0]["id"] == "k123456CNTRL"


@pytest.mark.asyncio
async def test_request_failure_has_unknown_write_outcome_and_no_automatic_retry(monkeypatch):
    calls = []
    def reply(request):
        calls.append(request)
        raise httpx.ReadTimeout(TOKEN, request=request)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kw))
    result = await node({"operation": "delete_device", "device_id": DEVICE}).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unverified"
    assert len(calls) == 1 and TOKEN not in str(result)


@pytest.mark.parametrize("value", ["https://evil.test", "../other", "a/b", "a?x=y", "a#frag", ".", "..", "a\n"])
def test_path_injection_rejected(value):
    with pytest.raises(ValueError):
        node({"operation": "get_device", "device_id": value})


@pytest.mark.parametrize("value", ["https://example.com/key", "tskey-auth-device", "tskey-client-client", "Bearer key", "key\r\nInjected:yes"])
def test_manual_credentials_reject_wrong_secret_kind(value):
    with pytest.raises(ValueError):
        native.TailscaleAPITokenCredential(api_token=value)


def test_credential_default_and_all_operations_covered():
    assert native.TailscaleAPITokenCredential(api_token=TOKEN).credential_type == native.FAMILY
    assert {row[0]["operation"] for row in CASES} == set(native.ROUTES)


@pytest.mark.asyncio
async def test_error_redaction_happens_before_message_truncation(monkeypatch):
    transport(monkeypatch, {"message": "x" * 1995 + TOKEN}, status=401)
    result = await node({"operation": "list_devices"}).execute({})
    assert result["status"] == "error" and len(result["error"]) <= 2000
    assert "tskey" not in result["error"]


@pytest.mark.asyncio
async def test_empty_name_resets_hostname_through_runtime_config_lens(monkeypatch):
    seen = transport(monkeypatch, raw=b"")
    output = await node({"operation": "set_device_name", "device_id": DEVICE, "name": ""}).execute({})
    assert output["status"] == "success"
    assert json.loads(seen[0].content) == {"name": ""}
