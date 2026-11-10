"""Traccar wire requests, response parsing and poll deduplication."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.traccar_node import TraccarTokenCredential, OPERATIONS

CREDENTIAL = {"credential_type": "traccar_token", "server_url": "https://demo.traccar.org", "api_token": "real-format-test-token"}

def node(config):
    return NodeFactory.create_node(node_id="traccar-test", node_type="automation-traccar", node_data={"config": config, "credentials": CREDENTIAL})

@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(OPERATIONS))
async def test_wire(monkeypatch, name):
    method, path, body_type = OPERATIONS[name]
    config = {"operation": name}
    if "{id}" in path: config["resource_id"] = 42
    if name.startswith("report_"): config.update(device_id=42, from_time="2026-01-01T00:00:00Z", to_time="2026-01-02T00:00:00Z")
    if body_type:
        config["body"] = {"DeviceBody": {"name": "Van", "uniqueId": "van-42"}, "GroupBody": {"name": "Fleet"}, "GeofenceBody": {"name": "Depot", "area": "CIRCLE (0 0, 100)"}, "CommandBody": {"deviceId": 42, "type": "positionSingle"}}[body_type.__name__]
    seen = []
    def handle(request):
        seen.append(request)
        assert request.method == method
        assert request.url.path == "/api" + path.replace("{id}", "42")
        assert request.headers["authorization"] == "Bearer real-format-test-token"
        if body_type:
            body = json.loads(request.content)
            assert all(body[k] == v for k,v in config["body"].items())
            if method == "PUT": assert body["id"] == 42
        if name.startswith("report_"):
            assert request.url.params["deviceId"] == "42"
            assert request.url.params["from"].startswith("2026-01-01")
        return httpx.Response(204) if method == "DELETE" else httpx.Response(200, json={"id": 42} if body_type or "{id}" in path else [{"id": 42}])
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c: yield c
    monkeypatch.setattr("nodes.traccar_node.guarded_async_client", client)
    result = await node(config).execute({})
    assert len(seen) == 1
    assert result["data"] is None if method == "DELETE" else result["data"]

@pytest.mark.asyncio
async def test_poll(monkeypatch):
    events = json.loads((Path(__file__).parent / "fixtures/traccar/events.json").read_text())
    n = node({"operation": "on_new_event", "device_id": 42})
    async def request(method, path, params=None, body=None):
        assert (method, path) == ("GET", "/reports/events")
        assert params["deviceId"] == 42 and params["from"] < params["to"]
        return events
    monkeypatch.setattr(n, "_request", request)
    # Exercise the shared seen-set implementation using an in-memory state seam.
    state = {}
    async def update(mutator, **kwargs):
        value, result = mutator(state.copy())
        if value is not None: state.update(value)
        return result
    monkeypatch.setattr(n, "_update_node_state", update)
    first = await n.execute({})
    assert first["events"] == []
    events.append({**events[0], "id": 43})
    fresh = await n.execute({})
    assert [e["id"] for e in fresh["events"]] == [43]
    assert "Device 42" in n.resolve_agent_event(fresh)["text"]
    second = await n.execute({})
    assert second["events"] == []
    assert not n.should_propagate_output(second, {"operation": "on_new_event"})

@pytest.mark.parametrize("url", ["http://demo.traccar.org", "https://user:password@example.com"])
def test_invalid_origin(url):
    with pytest.raises(ValueError): TraccarTokenCredential(**{**CREDENTIAL, "server_url": url})
