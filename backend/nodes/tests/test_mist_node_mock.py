"""Wire and lifecycle checks using examples from Mist's published OpenAPI."""
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError
from nodes import mist_node as m

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/mist/published_examples.json").read_text()
)
SITE = "72771e6a-6f5e-4de4-a5b9-1266c4197811"
ID = "487f6eca-6276-4993-bfeb-e3cbbbba3f08"
CREDENTIAL = {"credential_type": "mist_api_token", "api_token": "test-mist-token"}


def node(config):
    return m.MistNode(
        node_id="mist-test",
        node_type="automation-mist",
        node_data={"config": config},
        config=m.MistNodeConfig.model_validate(
            {"config": config, "credentials": CREDENTIAL}
        ),
        sio=Mock(),
    )


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c

    monkeypatch.setattr(m, "guarded_async_client", client)


# Independent endpoint expectations, not derived from the implementation table.
CASES = [
    ("get_account", "GET", "/self", {}),
    ("list_sites", "GET", "/orgs/{org_id}/sites", {"org_id": ID}),
    (
        "create_site",
        "POST",
        "/orgs/{org_id}/sites",
        {"org_id": ID, "name": "Mist Office", "timezone": "America/Los_Angeles"},
    ),
    ("get_site", "GET", "/sites/{site_id}", {"site_id": SITE}),
    (
        "update_site",
        "PUT",
        "/sites/{site_id}",
        {"site_id": SITE, "name": "Mist Office"},
    ),
    (
        "list_inventory",
        "GET",
        "/orgs/{org_id}/inventory",
        {"org_id": ID, "page": 2, "modified_after": 1703003296},
    ),
    ("list_devices", "GET", "/sites/{site_id}/devices", {"site_id": SITE}),
    (
        "get_device",
        "GET",
        "/sites/{site_id}/devices/{device_id}",
        {"site_id": SITE, "device_id": ID},
    ),
    ("list_device_stats", "GET", "/sites/{site_id}/stats/devices", {"site_id": SITE}),
    (
        "restart_device",
        "POST",
        "/sites/{site_id}/devices/{device_id}/restart",
        {"site_id": SITE, "device_id": ID, "member": 0},
    ),
    (
        "list_clients",
        "GET",
        "/sites/{site_id}/stats/clients",
        {"site_id": SITE, "start": 1703003296},
    ),
    ("list_wlans", "GET", "/sites/{site_id}/wlans", {"site_id": SITE}),
    (
        "get_wlan",
        "GET",
        "/sites/{site_id}/wlans/{wlan_id}",
        {"site_id": SITE, "wlan_id": ID},
    ),
    (
        "create_wlan",
        "POST",
        "/sites/{site_id}/wlans",
        {"site_id": SITE, "ssid": "corporate", "psk": "foryoureyesonly"},
    ),
    (
        "update_wlan",
        "PUT",
        "/sites/{site_id}/wlans/{wlan_id}",
        {"site_id": SITE, "wlan_id": ID, "ssid": "corporate", "enabled": False},
    ),
    (
        "delete_wlan",
        "DELETE",
        "/sites/{site_id}/wlans/{wlan_id}",
        {"site_id": SITE, "wlan_id": ID},
    ),
    (
        "search_device_events",
        "GET",
        "/sites/{site_id}/devices/events/search",
        {"site_id": SITE, "text": "Device connected", "search_after": "cursor"},
    ),
    (
        "search_alarms",
        "GET",
        "/sites/{site_id}/alarms/search",
        {"site_id": SITE, "acked": False},
    ),
    (
        "acknowledge_alarm",
        "POST",
        "/sites/{site_id}/alarms/{alarm_id}/ack",
        {"site_id": SITE, "alarm_id": ID, "note": "maintenance window"},
    ),
    (
        "unacknowledge_alarm",
        "POST",
        "/sites/{site_id}/alarms/{alarm_id}/unack",
        {"site_id": SITE, "alarm_id": ID, "note": "maintenance window"},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,config", CASES)
async def test_mist_operations(monkeypatch, operation, method, path, config):
    expected = EXAMPLES["responses"].get(operation, {})
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == method
        assert request.url.path == "/api/v1" + path.format(**config)
        assert request.url.host == "api.mist.com"
        assert request.headers["Authorization"] == "Token test-mist-token"
        if method in {"GET", "DELETE"}:
            assert not request.content
        if operation == "create_wlan":
            assert json.loads(request.content) == {
                "ssid": "corporate",
                "auth": {"type": "psk", "psk": "foryoureyesonly"},
                "enabled": False,
            }
        if operation == "update_wlan":
            assert json.loads(request.content) == {
                "ssid": "corporate",
                "enabled": False,
            }
        if operation == "restart_device":
            assert json.loads(request.content) == {"member": 0}
        if operation == "list_inventory":
            assert request.url.params["page"] == "2"
            assert request.url.params["modified_after"] == "1703003296"
        if operation == "search_alarms":
            assert request.url.params["acked"] == "false"
        if operation == "search_device_events":
            assert request.url.params["search_after"] == "cursor"
        return httpx.Response(200, json=expected)

    transport(monkeypatch, handler)
    result = await node({"operation": operation, **config}).execute({})
    assert result["data"] == expected
    assert len(calls) == 1


@pytest.mark.parametrize(
    "value", ["https://evil.example", "Token secret", "abc\nInjected", "{{TOKEN}}"]
)
def test_mist_rejects_bad_tokens(value):
    with pytest.raises((ValidationError, ValueError)):
        m.MistAPITokenCredential(api_token=value)


def test_mist_manual_credential_and_region():
    assert (
        m.MistAPITokenCredential(api_token="abc123").credential_type == "mist_api_token"
    )
    with pytest.raises(ValidationError):
        m.MistAPITokenCredential(
            api_token="abc123", api_base_url="https://api.mist.com.evil.example"
        )
    with pytest.raises(ValidationError):
        node({"operation": "get_site", "site_id": "../other"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,event_name",
    [("on_device_status", "device_updowns"), ("on_alarm", "alarms")],
)
async def test_mist_webhook_lifecycle_and_agent(monkeypatch, operation, event_name):
    event = EXAMPLES["events"][event_name]
    config = {"operation": operation, "site_id": SITE}
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["topics"] == [event["topic"]]
            assert body["type"] == "http-post" and body["verify_cert"] is True
            assert body["url"] == "https://test.hooks.example.test/hook"
            assert len(body["secret"]) == 64
            return httpx.Response(200, json={"id": ID})
        assert request.method == "DELETE"
        assert request.url.path == f"/api/v1/sites/{SITE}/webhooks/{ID}"
        return httpx.Response(200, json={})

    transport(monkeypatch, handler)
    registered = await m.MistNode._register_external_webhook(
        webhook_url="https://test.hooks.example.test/hook",
        credential=CREDENTIAL,
        config=config,
        node_id="test",
    )
    config.update(registered)
    body = json.dumps(event).encode()
    signature = hmac.new(
        registered["signing_secret"].encode(), body, hashlib.sha256
    ).hexdigest()
    assert m.MistNode.verify_webhook_signature(
        body, {"X-Mist-Signature-v2": signature}, config
    )
    assert not m.MistNode.verify_webhook_signature(
        body + b" ", {"x-mist-signature-v2": signature}, config
    )
    assert not m.MistNode.verify_webhook_signature(body, {}, config)
    assert not m.MistNode.verify_webhook_signature(
        body, {"x-mist-signature-v2": signature}, {}
    )
    assert m.MistNode.filter_trigger_payload(event, config)
    assert not m.MistNode.filter_trigger_payload(event, {**config, "site_id": ID})
    output = m.MistNode.resolve_trigger_payload(event, config)
    agent = m.MistNode.resolve_agent_event(output)
    assert SITE in agent["text"] and event["events"][0]["type"] in agent["text"]
    assert (
        m.MistNode.resolve_agent_event(
            m.MistNode.resolve_trigger_payload({"topic": "ping"}, config)
        )
        is None
    )
    await m.MistNode._unregister_external_webhook(
        credential=CREDENTIAL, config=config, node_id="test"
    )
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_mist_errors_and_empty_delete(monkeypatch):
    transport(
        monkeypatch, lambda req: httpx.Response(401, json={"detail": "Invalid token"})
    )
    with pytest.raises(ValueError, match="401: Invalid token"):
        await node({"operation": "get_account"}).execute({})
    transport(monkeypatch, lambda req: httpx.Response(204))
    assert (
        await node(
            {"operation": "delete_wlan", "site_id": SITE, "wlan_id": ID}
        ).execute({})
    )["data"] == {}
