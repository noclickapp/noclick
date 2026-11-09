"""Native factory tests against a mock HTTP transport; never send real notifications."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from nodes import pushcut_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/pushcut/operations.json").read_text())
TOKEN = "pushcut-synthetic-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="pushcut-test", node_type="automation-pushcut",
        node_data={"config": config, "credentials": {"credential_type": "pushcut_api_key", "api_key": TOKEN, **credential}})


def transport(monkeypatch, response):
    calls = []
    def respond(request):
        calls.append(request)
        return response
    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_pushcut_each_operation_uses_exact_provider_route_and_wire_fields(monkeypatch, case):
    response = httpx.Response(case.get("status", 200), **({"json": case["response"]} if "response" in case else {}))
    calls = transport(monkeypatch, response)
    obj = node(case["config"])
    out = await obj.execute({})
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert request.url.host == "api.pushcut.io"
    assert request.url.raw_path.split(b"?")[0].decode() == case["path"]
    assert request.headers["API-Key"] == TOKEN
    assert "authorization" not in request.headers
    assert dict(request.url.params) == case.get("query", {})
    if "body" in case:
        assert json.loads(request.content) == case["body"]
    else:
        assert not request.content
    assert out["status"] == "success"
    assert out["http_status"] == case.get("status", 200)
    if "response" in case:
        assert out["items" if isinstance(case["response"], list) else "data"] == case["response"]
    if case["method"] != "GET":
        assert out["provider_acknowledged"] is True
        assert "delivered" not in out


@pytest.mark.asyncio
async def test_pushcut_native_factory_evidence_empty_account(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json=[]))
    out = await node({"operation": "list_devices"}).run({})
    assert out["items"] == [] and out["status"] == "success"
    assert native.PushcutNode.connection_evidence.operation == "list_devices"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_pushcut_provider_rejection_no_retry_or_credential_leak(monkeypatch, status):
    calls = transport(monkeypatch, httpx.Response(status, json={"error": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_devices"}).execute({})
    assert "Rejected" in str(exc.value) and str(status) in str(exc.value)
    assert TOKEN not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_pushcut_execution_binary_response_is_file(monkeypatch):
    transport(monkeypatch, httpx.Response(200, content=b"\x00\xffbinary", headers={"content-type": "application/octet-stream"}))
    out = await node({"operation": "execute_action", "homekit": "Downstairs Lights On"}).execute({})
    assert isinstance(out["file"], BinaryOutput)
    assert out["file"].data == b"\x00\xffbinary"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, json={"error": "bad shape"}), httpx.Response(200), httpx.Response(200, text="not JSON")])
async def test_pushcut_malformed_evidence_never_passes(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "list_devices"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "execute_action"},
    {"operation": "execute_action", "shortcut": "A", "homekit": "B"},
    {"operation": "update_widget", "widget_name": "MyWidget"},
    {"operation": "update_widget", "widget_name": "MyWidget", "onTap": {"action": "runShortcut"}},
    {"operation": "move_image", "image_name": "A", "destination": "A"},
    {"operation": "send_notification", "notification_name": ".."},
    {"operation": "send_notification", "notification_name": "A", "actions": [{"url": "https://www.pushcut.io"}]},
    {"operation": "create_subscription", "actionName": "A", "url": "file:///etc/passwd"},
    {"operation": "list_devices", "arbitrary": "ignored?"},
])
def test_pushcut_rejects_invalid_config(config):
    with pytest.raises(ValidationError):
        TypeAdapter(native.Operation).validate_python(config)


def test_pushcut_manual_credential_has_default_type_and_cleans_key():
    cred = native.PushcutApiKeyCredential(api_key="  " + TOKEN + "  ")
    assert cred.credential_type == "pushcut_api_key" and cred.api_key == TOKEN
    for key in ["https://api.pushcut.io/secret", "<token>", "bad\nkey"]:
        with pytest.raises(ValidationError):
            native.PushcutApiKeyCredential(api_key=key)
    with pytest.raises(ValidationError):
        native.PushcutApiKeyCredential(api_key=TOKEN, credential_type="another_provider")


@pytest.mark.asyncio
async def test_pushcut_documented_default_action_without_name_and_background_request(monkeypatch):
    calls = transport(monkeypatch, httpx.Response(200, json={"id": "notification-42"}))
    # https://www.pushcut.io/support/notifications#webhook-json
    await node({"operation": "send_notification", "notification_name": "MyNotification",
                "defaultAction": {"input": "/myFolder"},
                "actions": [{"name": "Turn On Lights",
                             "url": "https://maker.ifttt.com/trigger/lights_on/with/key/noTaReaLkEY",
                             "urlBackgroundOptions": {"httpMethod": "GET"}}]}).execute({})
    body = json.loads(calls[0].content)
    assert body["defaultAction"] == {"input": "/myFolder"}
    assert body["actions"][0]["urlBackgroundOptions"] == {"httpMethod": "GET"}


def test_pushcut_native_factory_refuses_other_provider_family():
    data = {"config": {"operation": "list_devices"}, "credentials": {"credential_type": "other_api_key", "api_key": TOKEN}}
    assert native.PushcutNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError, match="Pushcut API key credential"):
        node(data["config"], credential_type="other_api_key")


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200), httpx.Response(200, json={"message": "unconfirmed"})])
async def test_pushcut_notification_requires_provider_acknowledgement_id(monkeypatch, response):
    calls = transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "send_notification", "notification_name": "MyNotification"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_pushcut_redacts_long_secret_before_truncating_provider_error(monkeypatch):
    key = "secret-prefix-" + "a" * 2000
    transport(monkeypatch, httpx.Response(401, json={"error": "Rejected " + key}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_devices"}, api_key=key).execute({})
    assert "secret-prefix-" not in str(exc.value)
