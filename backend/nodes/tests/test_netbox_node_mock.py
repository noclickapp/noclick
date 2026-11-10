"""Exercise native NetBox dispatch and webhook lifecycle at the HTTP boundary."""
import hashlib
import hmac
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import netbox_node as nb
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "netbox_api_token", "base_url": "https://netbox.example.com", "api_token": "fixture-netbox-token"}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "netbox.example.com"
        assert AUTH["api_token"] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(nb, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(node_type="automation-netbox", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(auth), user_id=USER)


@pytest.mark.parametrize("operation,arguments,method,path,body", [
    ("list_devices", {"site_id": 2, "status": "active", "offset": 10}, "GET", "/api/dcim/devices/", None),
    ("get_device", {"id": 7}, "GET", "/api/dcim/devices/7/", None),
    ("create_device", {"name": "router", "device_type": 1, "role": 2, "site": 3}, "POST", "/api/dcim/devices/", {"name": "router", "device_type": 1, "role": 2, "site": 3}),
    ("update_device", {"id": 7, "primary_ip4": 8}, "PATCH", "/api/dcim/devices/7/", {"primary_ip4": 8}),
    ("list_sites", {}, "GET", "/api/dcim/sites/", None),
    ("get_site", {"id": 7}, "GET", "/api/dcim/sites/7/", None),
    ("create_site", {"name": "Site 1", "slug": "site-1"}, "POST", "/api/dcim/sites/", {"name": "Site 1", "slug": "site-1"}),
    ("update_site", {"id": 7, "status": "active"}, "PATCH", "/api/dcim/sites/7/", {"status": "active"}),
    ("list_ip_addresses", {"address": "192.0.2.1/24"}, "GET", "/api/ipam/ip-addresses/", None),
    ("get_ip_address", {"id": 7}, "GET", "/api/ipam/ip-addresses/7/", None),
    ("create_ip_address", {"address": "192.0.2.1/24", "assigned_object_type": "dcim.interface", "assigned_object_id": 4}, "POST", "/api/ipam/ip-addresses/", {"address": "192.0.2.1/24", "assigned_object_type": "dcim.interface", "assigned_object_id": 4}),
    ("update_ip_address", {"id": 7, "dns_name": "router.example.com"}, "PATCH", "/api/ipam/ip-addresses/7/", {"dns_name": "router.example.com"}),
    ("allocate_ip_address", {"id": 7}, "POST", "/api/ipam/prefixes/7/available-ips/", [{}]),
    ("delete_ip_address", {"id": 7}, "DELETE", "/api/ipam/ip-addresses/7/", None),
    ("list_prefixes", {"vrf_id": 2}, "GET", "/api/ipam/prefixes/", None),
    ("get_prefix", {"id": 7}, "GET", "/api/ipam/prefixes/7/", None),
    ("create_prefix", {"prefix": "192.0.2.0/24", "is_pool": False}, "POST", "/api/ipam/prefixes/", {"prefix": "192.0.2.0/24", "is_pool": False}),
    ("update_prefix", {"id": 7, "custom_fields": {"automation": "ready"}}, "PATCH", "/api/ipam/prefixes/7/", {"custom_fields": {"automation": "ready"}}),
    ("list_virtual_machines", {"cluster_id": 2}, "GET", "/api/virtualization/virtual-machines/", None),
    ("get_virtual_machine", {"id": 7}, "GET", "/api/virtualization/virtual-machines/7/", None),
    ("create_virtual_machine", {"name": "vm-1", "vcpus": 2, "memory": 4096}, "POST", "/api/virtualization/virtual-machines/", {"name": "vm-1", "vcpus": 2.0, "memory": 4096}),
    ("update_virtual_machine", {"id": 7, "status": "offline"}, "PATCH", "/api/virtualization/virtual-machines/7/", {"status": "offline"}),
    ("list_interfaces", {"device_id": 2}, "GET", "/api/dcim/interfaces/", None),
    ("update_interface", {"id": 7, "enabled": False, "mtu": 1500}, "PATCH", "/api/dcim/interfaces/7/", {"enabled": False, "mtu": 1500}),
])
async def test_dispatch(transport, operation, arguments, method, path, body):
    requests, replies = transport
    payload = {"count": 1, "next": None, "previous": None, "results": [{"id": 7}]} if operation.startswith("list_") else {"id": 7}
    if operation == "allocate_ip_address":
        payload = [payload]
    replies.append((204 if method == "DELETE" else 201 if method == "POST" else 200, None if method == "DELETE" else payload))
    output = await run(operation, arguments)
    assert output["status"] == "success", output
    assert len(requests) == 1
    req = requests[0]
    assert (req.method, req.url.path) == (method, path)
    assert req.headers["Authorization"] == "Token " + AUTH["api_token"]
    assert json.loads(req.content) == body if body is not None else not req.content
    if operation.startswith("list_"):
        assert dict(req.url.params) == {"limit": "50", "offset": "0", **{k: str(v) for k, v in arguments.items()}}
        assert output["next_offset"] is None


async def test_v2_token_and_continuation(transport):
    requests, replies = transport
    replies.append((200, {"count": 3, "next": "https://untrusted.example/steal", "previous": None, "results": [{"id": 7}]}))
    output = await run("list_sites", {"offset": 1}, {**AUTH, "api_token": "nbt_key.token"})
    assert requests[0].headers["Authorization"] == "Bearer nbt_key.token"
    assert output["next_offset"] == 2 and output["has_more"] is True
    assert len(requests) == 1


@pytest.mark.parametrize("code", [301, 401, 403, 429, 500])
async def test_rejection_keeps_provider_message(transport, code):
    requests, replies = transport
    replies.append((code, {"detail": "Invalid token."}))
    with pytest.raises(ValueError, match=r"Invalid token\."):
        await run("list_sites")
    assert len(requests) == 1


async def test_refuse_empty_patch(transport):
    requests, replies = transport
    with pytest.raises(ValueError, match="at least one field"):
        await run("update_device", {"id": 1})
    assert not requests


async def test_ssrf_guard(monkeypatch):
    monkeypatch.delenv("OUTBOUND_ALLOW_PRIVATE_IPS", raising=False)
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)
    def never_send(request):
        pytest.fail("A private target reached the transport")
    native = ssrf.guarded_async_client
    monkeypatch.setattr(nb, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(never_send)))
    with pytest.raises(ssrf.SSRFError, match="non-public"):
        await run("list_sites", auth={**AUTH, "base_url": "https://127.0.0.1"})


@pytest.mark.parametrize("field,value", [("base_url", "http://netbox.example.com"), ("base_url", "https://user:pass@netbox.example.com"), ("api_token", "Bearer token"), ("api_token", "token\nheader")])
def test_credential_rejects_bad_input(field, value):
    with pytest.raises(ValueError):
        nb.NetBoxTokenCredential.model_validate({**AUTH, field: value})


def test_credential_manual_default():
    credential = nb.NetBoxTokenCredential(base_url="netbox.example.com", api_token="fixture-netbox-token")
    assert credential.credential_type == "netbox_api_token"
    assert credential.base_url == AUTH["base_url"]


async def test_webhook_lifecycle(transport):
    requests, replies = transport
    replies.extend([(201, {"id": 10}), (201, {"id": 20}), (204, None), (204, None)])
    registration = await nb.NetBoxNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/event", credential=AUTH, config={"object_type": "dcim.device"}, node_id="example")
    assert registration["external_webhook_id"] == "10:20"
    webhook = json.loads(requests[0].content)
    assert webhook == {"name": "NoClick example", "payload_url": "https://hooks.hooks.example.test/event", "http_method": "POST", "http_content_type": "application/json", "secret": registration["signing_secret"], "ssl_verification": True}
    assert json.loads(requests[1].content) == {"name": "NoClick example", "object_types": ["dcim.device"], "event_types": ["object_created"], "action_type": "webhook", "action_object_type": "extras.webhook", "action_object_id": 10, "enabled": True}
    await nb.NetBoxNode._unregister_external_webhook(credential=AUTH, config=registration, node_id="example")
    assert [(r.method, r.url.path) for r in requests[2:]] == [("DELETE", "/api/extras/event-rules/20/"), ("DELETE", "/api/extras/webhooks/10/")]


async def test_registration_rolls_back_webhook_if_rule_fails(transport):
    requests, replies = transport
    replies.extend([(201, {"id": 10}), (403, {"detail": "Permission denied"}), (204, None)])
    with pytest.raises(ValueError, match="Permission denied"):
        await nb.NetBoxNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/event", credential=AUTH, config={}, node_id="example")
    assert requests[-1].method == "DELETE" and requests[-1].url.path == "/api/extras/webhooks/10/"


def test_documented_delivery_signature_and_agent_event():
    payload = json.loads((Path(__file__).parent / "fixtures/netbox/site_created.json").read_text())
    body = json.dumps(payload).encode()
    config = {"signing_secret": "fixture-secret", "object_type": "dcim.site"}
    signature = hmac.new(config["signing_secret"].encode(), body, hashlib.sha512).hexdigest()
    assert nb.NetBoxNode.verify_webhook_signature(body, {"X-Hook-Signature": signature}, config)
    assert not nb.NetBoxNode.verify_webhook_signature(body + b" ", {"X-Hook-Signature": signature}, config)
    assert not nb.NetBoxNode.verify_webhook_signature(body, {}, config)
    assert not nb.NetBoxNode.verify_webhook_signature(body, {"X-Hook-Signature": signature}, {})
    assert nb.NetBoxNode.filter_trigger_payload(payload, config)
    assert not nb.NetBoxNode.filter_trigger_payload(payload, {"object_type": "dcim.device"})
    assert not nb.NetBoxNode.filter_trigger_payload({**payload, "event": "updated"}, config)
    output = nb.NetBoxNode.resolve_trigger_payload(payload, config)
    event = nb.NetBoxNode.resolve_agent_event(output)
    assert event["conversation_key"] == "dcim.site:4"
    for text in ["Site 1", "jstretch", "/dcim/sites/4/", "created", "ID 4"]:
        assert text in event["text"]
