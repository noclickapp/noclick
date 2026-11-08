"""Exercise HERE Tracking through discovery and the actual node factory.

Published examples are excerpted in fixtures/here/examples.json. Other responses
below are synthetic; no account or live provider mutation is used.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import here_node as here
from nodes.core.registry import NODE_REGISTRY, NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/here/examples.json").read_text())
TOKEN = "synthetic-here-user-token"
UUID = "d0c29690-5d26-4cf1-a37e-b7816e72cb99"
LOCATION = "LOC-61a3fba0-cb44-405f-816c-c2aec73a1add"
TRACKING = "HERE-540bb24b-0d57-4f8c-aeaf-6c91cd0aff8d"
CIRCLE = {"type": "circle", "definition": {"center": {"lat": 52.5, "lng": 13.4}, "radius": 100}}
RULE = {"type": "dwelling", "threshold": {"durationS": 3600}}
LOCATION_BODY = {"name": "Rostock Port", "location": {"lat": 54.155147, "lng": 12.12204}}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(operation, config=None, **credential):
    return NodeFactory.create_node(node_id="here-fixture", node_type="automation-here", node_data={
        "config": {"operation": operation, **(config or {})},
        "credentials": {"credential_type": "here_user_token", "access_token": TOKEN, **credential}})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    def respond(request):
        requests.append(request)
        return replies.pop(0)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(here, "guarded_async_client", client)
    return requests, replies


CASES = [
    ("list_devices", {}, "GET", "/users/v2/devices", {"count": 1, "data": [{"trackingId": TRACKING}]}),
    ("list_shadows", {}, "GET", "/shadows/v4", {"count": 0, "limit": 100, "items": []}),
    ("get_shadow", {"tracking_id": TRACKING}, "GET", "/shadows/v2/" + TRACKING, EXAMPLES["shadow"]),
    ("get_traces", {"tracking_id": TRACKING}, "GET", "/traces/v2/" + TRACKING, EXAMPLES["traces"]),
    ("list_geofences", {}, "GET", "/geofences/v2", EXAMPLES["geofences"]),
    ("get_geofence", {"geofence_id": UUID}, "GET", "/geofences/v2/" + UUID, EXAMPLES["geofence"]),
    ("create_geofence", {"geofence": CIRCLE}, "POST", "/geofences/v2", {"id": UUID}),
    ("update_geofence", {"geofence_id": UUID, "geofence": CIRCLE}, "PUT", "/geofences/v2/" + UUID, {"id": UUID, "geofence": CIRCLE}),
    ("delete_geofence", {"geofence_id": UUID}, "DELETE", "/geofences/v2/" + UUID, None),
    ("list_locations", {}, "GET", "/locations/v4", {"count": 1, "limit": 100, "items": [EXAMPLES["location"]]}),
    ("get_location", {"location_id": LOCATION}, "GET", "/locations/v4/" + LOCATION, EXAMPLES["location"]),
    ("create_location", {"location": LOCATION_BODY}, "POST", "/locations/v4", {"locationId": LOCATION}),
    ("update_location", {"location_id": LOCATION, "location": LOCATION_BODY}, "PUT", "/locations/v4/" + LOCATION, EXAMPLES["location"]),
    ("delete_location", {"location_id": LOCATION}, "DELETE", "/locations/v4/" + LOCATION, None),
    ("list_rules", {}, "GET", "/rules/v4", EXAMPLES["rules"]),
    ("get_rule", {"rule_id": UUID}, "GET", "/rules/v4/" + UUID, {"ruleId": UUID, "rule": RULE}),
    ("create_rule", {"rule": RULE}, "POST", "/rules/v4", {"ruleId": UUID}),
    ("update_rule", {"rule_id": UUID, "rule": RULE}, "PUT", "/rules/v4/" + UUID, {"ruleId": UUID, "rule": RULE}),
    ("delete_rule", {"rule_id": UUID}, "DELETE", "/rules/v4/" + UUID, None),
    ("get_device_metadata", {"tracking_id": TRACKING}, "GET", "/metadata/v2/devices/" + TRACKING, {"id": TRACKING, "data": {"priority": "high"}}),
    ("set_device_metadata", {"tracking_id": TRACKING, "metadata": {"priority": "high"}}, "PUT", "/metadata/v2/devices/" + TRACKING, {"id": TRACKING, "data": {"priority": "high"}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,payload", CASES)
async def test_here_all_operations_have_one_documented_request(transport, operation, config, method, path, payload):
    requests, replies = transport
    replies.append(httpx.Response(204) if payload is None else httpx.Response(201 if operation.startswith("create_") else 200, json=payload))
    result = await make_node(operation, config, project_id="project-fixture").execute({})
    assert NODE_REGISTRY["automation-here"] is here.HereNode
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.host, request.url.path) == (method, "tracking.api.here.com", path)
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert ("projectId" in request.url.params) == ("{" not in here.ROUTES[operation][1])
    if operation.startswith(("create_", "update_")):
        assert json.loads(request.content) == config[operation.split("_", 1)[1]]
    if operation == "set_device_metadata":
        assert json.loads(request.content) == config["metadata"]
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,wire_key,cursor_key,collection", [
    ("list_devices", "count", "pageToken", "data"),
    ("list_geofences", "count", "pageToken", "data"),
    ("list_locations", "limit", "nextPageToken", "items"),
    ("list_rules", "limit", "nextPageToken", "items"),
    ("list_shadows", "limit", "nextPageToken", "items"),
])
async def test_here_page_tokens_and_sizes(transport, operation, wire_key, cursor_key, collection):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"count": 0, "limit": 5, collection: [], cursor_key: "next-opaque"}))
    result = await make_node(operation, {"page_size": 5, "page_token": "previous-opaque"}).execute({})
    assert result["next_page_token"] == "next-opaque"
    assert dict(requests[0].url.params) == {wire_key: "5", "pageToken": "previous-opaque"}
    replies.append(httpx.Response(200, json={collection: [], cursor_key: "previous-opaque"}))
    with pytest.raises(ValueError, match="non-advancing"):
        await make_node(operation, {"page_token": "previous-opaque"}).execute({})


@pytest.mark.asyncio
async def test_here_virtual_device_and_trace_filters(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"data": [], "count": 0}))
    await make_node("get_traces", {"tracking_id": "external-device", "app_id": "app-12345678", "after": 1000,
        "before": 2000, "smooth": False, "outliers": True, "mode": "normal"}, project_id="not-on-this-route").execute({})
    assert dict(requests[0].url.params) == {"appId": "app-12345678", "count": "100", "before": "2000.0", "after": "1000.0", "outliers": "true", "smooth": "false", "mode": "normal"}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 429, 500])
async def test_here_errors_never_become_connection_success(transport, code):
    requests, replies = transport
    replies.append(httpx.Response(code, json={"error": "Unauthorized", "message": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as caught:
        await make_node("list_devices").execute({})
    assert TOKEN not in str(caught.value)
    assert f"HTTP {code}" in str(caught.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(200, text="login", headers={"content-type": "text/html"}),
    httpx.Response(200, json={"error": "bad token"}), httpx.Response(200, json={"data": {}}),
    httpx.Response(200, text="invalid", headers={"content-type": "application/json"})])
async def test_here_malformed_responses_fail_closed(transport, reply):
    transport[1].append(reply)
    with pytest.raises(ValueError):
        await make_node("list_devices").execute({})


@pytest.mark.asyncio
async def test_here_redacts_echoed_token_without_mutating_other_metadata(transport):
    transport[1].append(httpx.Response(200, json={"id": TRACKING, "data": {"note": TOKEN, "priority": "high"}}))
    result = await make_node("get_device_metadata", {"tracking_id": TRACKING}).execute({})
    assert result["data"]["data"] == {"note": "[redacted]", "priority": "high"}


@pytest.mark.parametrize("operation,config", [
    ("get_shadow", {"tracking_id": "../foreign"}),
    ("get_shadow", {"tracking_id": "https://example.test"}),
    ("get_geofence", {"geofence_id": "not-a-uuid"}),
    ("get_location", {"location_id": UUID}),
    ("create_geofence", {"geofence": {"type": "circle", "definition": {"center": {"lat": 100, "lng": 0}, "radius": 1}}}),
    ("create_geofence", {"geofence": {"type": "polygon", "definition": {"points": [{"lat": 0, "lng": 0}]}}}),
    ("create_location", {"location": {"name": "Missing coordinates"}}),
    ("create_rule", {"rule": {"type": "dwelling"}}),
    ("create_rule", {"rule": {"type": "online", "threshold": {"durationS": 1}}}),
    ("set_device_metadata", {"tracking_id": TRACKING, "metadata": {"text": "x" * 1000}}),
    ("get_traces", {"tracking_id": TRACKING, "after": 3000, "before": 2000}),
])
def test_here_rejects_invalid_configs_before_http(operation, config):
    with pytest.raises(ValueError):
        make_node(operation, config)


def test_here_manual_credential_tag_default_and_token_requirements():
    assert here.HereUserTokenCredential(access_token=TOKEN).credential_type == "here_user_token"
    for value in ["https://example.test/key", "Bearer " + TOKEN, "<token>"]:
        with pytest.raises(ValueError):
            here.HereUserTokenCredential(access_token=value)
    with pytest.raises(ValidationError):
        here.HereUserTokenCredential(credential_type="foreign_token", access_token=TOKEN)
