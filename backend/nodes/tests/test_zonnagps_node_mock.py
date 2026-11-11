"""Exercise ZonnaGPS requests and signed events against provider-owned examples.

These tests use no live credentials and pin route, method, parameter and lifecycle behavior.
"""
import hashlib
import hmac
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError
from nodes.zonnagps_node import (
    BASE_URL, EVENTS, OPERATIONS, ZonnaGPSNode, ZonnaGPSNodeConfig,
    ZonnaGPSAPITokenCredential,
)

FIXTURES = Path(__file__).parent / "fixtures/zonnagps"
CREDENTIAL = {"credential_type": "zonnagps_api_token", "api_token": "test-zonna-key"}


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


def node(config):
    return ZonnaGPSNode(node_id="zonna-test", node_type="automation-zonnagps", sio=Mock(),
        node_data={"config": config}, config=ZonnaGPSNodeConfig.model_validate({"config": config, "credentials": CREDENTIAL}))


CASES = [
    ({"operation": "list_assets", "search": "1234ABC", "page": 2}, "GET", "/assets", {"search": "1234ABC", "page": "2"}, None),
    ({"operation": "get_asset", "asset": 42}, "GET", "/assets/42", {}, None),
    ({"operation": "get_latest_position", "asset": 42}, "GET", "/assets/42/position", {}, None),
    ({"operation": "list_positions", "asset": 42, "from_time": "2026-10-01T00:00:00Z", "to_time": "2026-10-02T00:00:00Z"}, "GET", "/assets/42/positions", {"from": "2026-10-01T00:00:00Z", "to": "2026-10-02T00:00:00Z"}, None),
    ({"operation": "list_alarms", "per_page": 20}, "GET", "/alarms", {"per_page": "20"}, None),
    ({"operation": "list_drivers", "search": "Ana", "include_inactive": True}, "GET", "/drivers", {"search": "Ana", "include_inactive": "true"}, None),
    ({"operation": "create_driver", **fixture("driver")}, "POST", "/drivers", {}, fixture("driver")),
    ({"operation": "update_driver", "id": 12, "phone": None}, "PATCH", "/drivers/12", {}, {"phone": None}),
    ({"operation": "deactivate_driver", "id": 12}, "DELETE", "/drivers/12", {}, None),
    ({"operation": "create_place", **fixture("place")}, "POST", "/places", {}, fixture("place")),
    ({"operation": "update_place", "id": 12, "is_active": False}, "PATCH", "/places/12", {}, {"is_active": False}),
    ({"operation": "deactivate_place", "id": 12}, "DELETE", "/places/12", {}, None),
    ({"operation": "create_geofence", **fixture("geofence")}, "POST", "/geofences", {}, fixture("geofence")),
    ({"operation": "update_geofence", "id": 12, "radius_meters": 100}, "PATCH", "/geofences/12", {}, {"radius_meters": 100}),
    ({"operation": "deactivate_geofence", "id": 12}, "DELETE", "/geofences/12", {}, None),
    ({"operation": "assign_driver", "id": 42, **fixture("assignment")}, "PUT", "/assets/42/driver", {}, fixture("assignment")),
    ({"operation": "list_webhooks"}, "GET", "/webhooks", {}, None),
    ({"operation": "get_report", "dataset": "vehicle-daily", "from_time": "2026-10-01", "to_time": "2026-10-31", "per_page": 1000}, "GET", "/reports/vehicle-daily", {"from": "2026-10-01", "to": "2026-10-31", "per_page": "1000", "format": "json"}, None),
]


@pytest.fixture
def transport(monkeypatch):
    responses = []
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer test-zonna-key"
        assert str(request.url).startswith(BASE_URL)
        status, payload = responses.pop(0) if responses else (200, {"data": {"id": 12}})
        return httpx.Response(status, json=payload)
    monkeypatch.setattr("nodes.zonnagps_node.guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))
    return requests, responses


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body", CASES)
async def test_contract_routes(transport, config, method, path, params, body):
    result = await node(config).execute({})
    request = transport[0][0]
    assert request.method == method
    assert request.url.path == "/api/public/v1" + path
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body
    assert len(transport[0]) == 1
    assert result["status"] == "success"


def test_all_actions_covered():
    assert {case[0]["operation"] for case in CASES} == set(OPERATIONS)


@pytest.mark.asyncio
async def test_pagination_and_null_position(transport):
    payload = {"data": [{"id": 42, "name": "Van"}], "meta": {"current_page": 2, "last_page": 3}}
    transport[1].append((200, payload))
    assert (await node({"operation": "list_assets", "page": 2}).execute({}))["meta"] == payload["meta"]
    transport[1].append((200, {"data": None}))
    assert (await node({"operation": "get_latest_position", "asset": 42}).execute({}))["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 409, 422, 429, 500])
async def test_provider_failures_are_not_success(transport, status):
    transport[1].append((status, {"error": {"message": "Provider rejection"}}))
    with pytest.raises(ValueError, match=f"HTTP {status}: Provider rejection"):
        await node({"operation": "list_assets"}).execute({})
    assert len(transport[0]) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_asset", "asset": 0},
    {"operation": "get_asset", "asset": "../drivers"},
    {"operation": "create_geofence", "name": "Zone", "center_latitude": 91, "center_longitude": 0, "radius_meters": 10},
    {"operation": "update_driver", "id": 12},
    {"operation": "list_assets", "per_page": 201},
    {"operation": "get_report", "dataset": "../drivers"},
])
def test_invalid_config(config):
    with pytest.raises(ValidationError):
        node(config)


def test_manual_credential_defaults():
    assert ZonnaGPSAPITokenCredential(api_token="real-zonna-key").credential_type == "zonnagps_api_token"
    for secret in ["https://example.com", "Bearer abc", "abc\n123"]:
        with pytest.raises(ValidationError):
            ZonnaGPSAPITokenCredential(api_token=secret)


def signature(body, timestamp=None):
    timestamp = str(timestamp if timestamp is not None else int(time.time()))
    digest = hmac.new(b"secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Zonna-Signature": f"t={timestamp},v1={digest}"}


@pytest.mark.parametrize("event", EVENTS)
def test_documented_events_and_signatures(event):
    payload = fixture(event)
    body = json.dumps(payload).encode()
    config = {"signing_secret": "secret", "event_type": "all"}
    assert ZonnaGPSNode.verify_webhook_signature(body, signature(body), config)
    assert not ZonnaGPSNode.verify_webhook_signature(body+b" ", signature(body), config)
    assert not ZonnaGPSNode.verify_webhook_signature(body, signature(body, int(time.time())-301), config)
    assert not ZonnaGPSNode.verify_webhook_signature(body, {}, config)
    assert not ZonnaGPSNode.verify_webhook_signature(body, signature(body), {})
    assert ZonnaGPSNode.filter_trigger_payload(payload, config)
    assert not ZonnaGPSNode.filter_trigger_payload(payload, {"event_type": "unknown"})
    assert ZonnaGPSNode.resolve_trigger_payload(payload, config) == payload
    turn = ZonnaGPSNode.resolve_agent_event(payload)
    assert event in turn["text"] and payload["id"] in turn["text"]
    assert str(payload["data"]["id"]) in turn["text"]


@pytest.mark.asyncio
async def test_registration_cleanup_and_manual_run(transport):
    transport[1].append((201, {"data": {"id": 7}, "secret": "one-time-secret"}))
    config = {"operation": "on_event", "event_type": "geofence.enter"}
    state = await ZonnaGPSNode._register_external_webhook(webhook_url="https://hooks.example.com/event", credential=CREDENTIAL, config=config, node_id="test")
    assert json.loads(transport[0][0].content) == {"url": "https://hooks.example.com/event", "events": ["geofence.enter"]}
    assert state == {"external_webhook_id": 7, "signing_secret": "one-time-secret"}
    await ZonnaGPSNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id="test")
    assert transport[0][1].method == "DELETE" and transport[0][1].url.path.endswith("/webhooks/7")
    assert (await node(config).execute({}))["status"] == "no_event"
    assert not ZonnaGPSNode.filter_trigger_payload({"event": "test.ping"}, {})


@pytest.mark.asyncio
async def test_redelivery_is_scoped_to_subscription(monkeypatch):
    redis = Mock()
    redis.set = AsyncMock(side_effect=[True, False, True])
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: redis)
    payload = fixture("geofence.enter")
    assert await ZonnaGPSNode.drop_trigger_event(payload, {"webhook_id": "a"}) is None
    assert await ZonnaGPSNode.drop_trigger_event(payload, {"webhook_id": "a"}) == "Duplicate ZonnaGPS event"
    assert await ZonnaGPSNode.drop_trigger_event(payload, {"webhook_id": "b"}) is None
    assert redis.set.call_args_list[0].args[0] != redis.set.call_args_list[2].args[0]
    redis.set.side_effect = RuntimeError("offline")
    assert await ZonnaGPSNode.drop_trigger_event(payload, {"webhook_id": "a"}) is None


@pytest.mark.parametrize("config", [
    {"operation": "list_positions", "asset": 42, "from_time": "2026-01-01T00:00:00Z", "to_time": "2026-03-01T00:00:00Z"},
    {"operation": "get_report", "dataset": "vehicle-daily", "from_time": "2026-10-31", "to_time": "2026-10-01"},
])
def test_date_ranges(config):
    with pytest.raises(ValidationError):
        node(config)


@pytest.mark.parametrize("header", ["t=1,v1=é", "t=nope,v1=abc", "t=1,t=2,v1=abc", "v1=abc", "", None])
def test_malformed_signatures_fail_closed(header):
    assert not ZonnaGPSNode.verify_webhook_signature(b"{}", {"X-Zonna-Signature": header}, {"signing_secret": "secret"})
