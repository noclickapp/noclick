"""Offline request/response regressions for Sauce Labs RDC v2; no account used."""
import base64
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from nodes import saucelabs_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "saucelabs_access_key", "username": "test-user", "access_key": "synthetic-sauce-access-key"}
SESSION = "123e4567-e89b-12d3-a456-426614174000"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="sauce-test", node_type="automation-saucelabs",
        node_data={"config": config, "credentials": CREDENTIAL if credential is None else credential})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30.0, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Explicit wire examples, independent of the node's routing table.
CASES = [
    ({"operation": "list_devices", "device_id": "iPhone.*"}, "GET", "/devices", {"deviceId": "iPhone.*"}, None, []),
    ({"operation": "list_device_status", "private_only": False, "state": "IN_USE", "device_name": "iPhone.*"}, "GET", "/devices/status", {"privateOnly": "false", "state": "IN_USE", "deviceName": "iPhone.*"}, None, {"devices": []}),
    ({"operation": "create_session", "device_name": "iPhone_16_real", "os": "ios", "tunnel_name": "tunnel", "tunnel_owner": "owner"}, "POST", "/sessions", {}, {"device": {"deviceName": "iPhone_16_real", "os": "ios"}, "configuration": {"sessionDuration": "PT1H", "tunnel": {"name": "tunnel", "owner": "owner"}}}, {"id": SESSION, "state": "CREATING"}),
    ({"operation": "list_sessions", "state": "ACTIVE"}, "GET", "/sessions", {"state": "ACTIVE"}, None, {"sessions": []}),
    ({"operation": "get_session", "session_id": SESSION}, "GET", f"/sessions/{SESSION}", {}, None, {"id": SESSION, "state": "ACTIVE", "error": None}),
    ({"operation": "close_session", "session_id": SESSION}, "DELETE", f"/sessions/{SESSION}", {"rebootDevice": "false"}, None, {"sessionId": SESSION, "state": "CLOSING"}),
    ({"operation": "execute_shell_command", "session_id": SESSION, "command": "ls /"}, "POST", f"/sessions/{SESSION}/device/executeShellCommand", {}, {"adbShellCommand": "ls /"}, {"stdout": "sdcard\n"}),
    ({"operation": "open_url", "session_id": SESSION, "url": "https://example.com"}, "POST", f"/sessions/{SESSION}/device/openUrl", {}, {"url": "https://example.com"}, None),
    ({"operation": "install_app", "session_id": SESSION, "app": "storage:filename=myapp.apk"}, "POST", f"/sessions/{SESSION}/device/installApp", {}, {"app": "storage:filename=myapp.apk", "enableInstrumentation": True, "launchAfterInstall": False}, {"installationId": "i1", "status": "PENDING"}),
    ({"operation": "list_app_installations", "session_id": SESSION}, "POST", f"/sessions/{SESSION}/device/listAppInstallations", {}, None, {"appInstallations": []}),
    ({"operation": "uninstall_app", "session_id": SESSION, "app_id": "com.saucelabs.mydemoapp.android"}, "POST", f"/sessions/{SESSION}/device/uninstallApp", {}, {"packageName": "com.saucelabs.mydemoapp.android"}, None),
    ({"operation": "apply_settings", "session_id": SESSION, "orientation": "PORTRAIT", "animations": False, "locale": "en_US"}, "POST", f"/sessions/{SESSION}/device/applySettings", {}, {"orientation": "PORTRAIT", "animations": False, "locale": "en_US"}, None),
    ({"operation": "start_appium", "session_id": SESSION}, "POST", f"/sessions/{SESSION}/appiumserver", {}, {"appiumVersion": "latest"}, {"url": "https://api.us-west-1.saucelabs.com/rdc/v2/sessions/s1/appium/wd/hub", "version": "stable"}),
    ({"operation": "get_appium", "session_id": SESSION}, "GET", f"/sessions/{SESSION}/appiumserver", {}, None, {"version": "stable"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body,reply", CASES)
async def test_wire_contract(monkeypatch, config, method, path, query, body, reply):
    requests = transport(monkeypatch, httpx.Response(204) if reply is None else httpx.Response(200, json=reply))
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == reply
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.us-west-1.saucelabs.com"
    assert request.url.path == "/rdc/v2" + path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"test-user:synthetic-sauce-access-key").decode()


@pytest.mark.asyncio
async def test_screenshot_returns_binary_marker(monkeypatch):
    png = b"\x89PNG\r\n\x1a\nfixture"
    requests = transport(monkeypatch, httpx.Response(200, content=png, headers={"Content-Type": "image/png"}))
    result = await node({"operation": "take_screenshot", "session_id": SESSION}).execute({})
    assert isinstance(result["data"], BinaryOutput) and result["data"].data == png
    assert requests[0].method == "POST" and requests[0].url.path.endswith("/device/takeScreenshot")
    assert requests[0].headers["Accept"] == "image/png" and not requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_errors_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, text="Rejected " + CREDENTIAL["access_key"]))
    result = await node({"operation": "list_sessions"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [[], {}, {"sessions": None}])
async def test_connection_read_requires_account_sessions_envelope(monkeypatch, reply):
    transport(monkeypatch, httpx.Response(200, json=reply))
    with pytest.raises(ValueError, match="device sessions"):
        await node({"operation": "list_sessions"}).execute({})


@pytest.mark.asyncio
async def test_connect_read_and_region(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={"sessions": [], "access_key": CREDENTIAL["access_key"]}))
    result = await node({"operation": "list_sessions"}, {**CREDENTIAL, "region": "eu-central-1"}).execute({})
    assert result["data"] == {"sessions": []}
    assert requests[0].url.host == "api.eu-central-1.saucelabs.com" and not requests[0].url.query
    assert native.SauceLabsNode.connection_evidence.operation == "list_sessions"


@pytest.mark.asyncio
async def test_ios_uninstall_sends_only_bundle_id(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(204))
    await node({"operation": "uninstall_app", "session_id": SESSION, "platform": "ios", "app_id": "com.saucelabs.rdc.demo"}).execute({})
    assert json.loads(requests[0].content) == {"bundleId": "com.saucelabs.rdc.demo"}


@pytest.mark.parametrize("config", [
    {"operation": "get_session", "session_id": "../other"},
    {"operation": "apply_settings", "session_id": SESSION},
    {"operation": "create_session", "device_name": "iPhone", "session_duration": "PT25H"},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        node(config).config


def test_manual_credentials_default_type_and_fixed_hosts():
    credential = native.SauceLabsAccessKeyCredential(username="test-user", access_key=CREDENTIAL["access_key"])
    assert credential.credential_type == "saucelabs_access_key"
    for change in [{"region": "attacker.example"}, {"username": "user:password"}, {"access_key": "https://example.com"}]:
        with pytest.raises(ValidationError):
            native.SauceLabsAccessKeyCredential.model_validate({**CREDENTIAL, **change})
