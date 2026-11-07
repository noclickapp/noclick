"""UptimeRobot v3 node contracts against the vendor's published routes."""

import json

import httpx
import pytest

from nodes.uptimerobot_node import (
    OPERATIONS,
    UptimeRobotNode,
    UptimeRobotNodeConfig,
    _request_parts,
)


def _node(operation, **fields):
    config = UptimeRobotNodeConfig.model_validate(
        {
            "config": {"operation": operation, **fields},
            "credentials": {
                "credential_type": "uptimerobot_api_key",
                "api_key": "test-main-key",
            },
        }
    )
    return UptimeRobotNode("qa", "automation-uptimerobot", {}, config=config)


def test_catalog_and_schema_cover_every_published_v3_operation():
    assert len(OPERATIONS) == 59
    assert len({(x["method"], x["path"]) for x in OPERATIONS.values()}) == 59
    assert {"list_monitors", "create_monitor", "get_monitor", "update_monitor", "delete_monitor"} <= OPERATIONS.keys()
    assert {"list_incidents", "create_maintenance_window", "list_status_pages"} <= OPERATIONS.keys()
    schema = UptimeRobotNode.get_config_schema()
    assert "UptimeRobotCreateMonitorConfig" in schema["$defs"]
    assert schema["$defs"]["UptimeRobotApiKeyCredential"]["properties"]["api_key"]["ui:widget"] == "password"


def test_monitor_creation_merges_guided_fields_over_json_extras():
    node = _node(
        "create_monitor",
        body_friendlyName="Production API",
        body_type="HTTP",
        body_url="https://example.com/health",
        body_interval=300,
        body_timeout=30,
        body_json='{"friendlyName":"old","customHttpHeaders":{"X-Test":"yes"}}',
    )
    path, params, body = _request_parts(node.config.config, OPERATIONS["create_monitor"])
    assert (path, params) == ("/monitors", {})
    assert body == {
        "friendlyName": "Production API",
        "type": "HTTP",
        "url": "https://example.com/health",
        "interval": 300.0,
        "timeout": 30.0,
        "customHttpHeaders": {"X-Test": "yes"},
    }


def test_monitor_creation_supplies_live_api_timeout_default_only_where_applicable():
    http = _node("create_monitor", body_type="HTTP", body_url="https://example.com")
    _, _, http_body = _request_parts(http.config.config, OPERATIONS["create_monitor"])
    assert http_body["timeout"] == 30

    heartbeat = _node("create_monitor", body_json='{"type":"HEARTBEAT","friendlyName":"Heartbeat"}')
    _, _, heartbeat_body = _request_parts(heartbeat.config.config, OPERATIONS["create_monitor"])
    assert "timeout" not in heartbeat_body


def test_path_segments_are_encoded_and_query_arrays_are_json():
    comment = _node("get_incident", id="a/b ?")
    path, params, body = _request_parts(comment.config.config, OPERATIONS["get_incident"])
    assert path == "/incidents/a%2Fb%20%3F"
    assert params == {}
    assert body is None

    listing = _node("list_monitors", query_limit=25, query_customField='["environment:qa"]')
    _, params, _ = _request_parts(listing.config.config, OPERATIONS["list_monitors"])
    assert params == {"limit": 25.0, "customField": ["environment:qa"]}


def test_bad_nested_json_fails_before_http():
    node = _node("create_monitor", body_json="not-json")
    with pytest.raises(ValueError, match="valid JSON"):
        _request_parts(node.config.config, OPERATIONS["create_monitor"])


@pytest.mark.asyncio
async def test_live_route_contract_for_create_get_update_delete(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["Authorization"] == "Bearer test-main-key"
        if request.method == "POST":
            return httpx.Response(201, json={"id": 42, "friendlyName": "Production API"})
        if request.method == "DELETE":
            return httpx.Response(200)
        return httpx.Response(200, json={"id": 42})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.uptimerobot_node.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert (await _node("create_monitor", body_friendlyName="Production API", body_type="HTTP", body_url="https://example.com", body_interval=300, body_timeout=30).execute({}))["status"] == "success"
    assert (await _node("get_monitor", id="42").execute({}))["status"] == "success"
    assert (await _node("update_monitor", id="42", body_friendlyName="Updated").execute({}))["status"] == "success"
    assert (await _node("delete_monitor", id="42").execute({}))["status"] == "success"
    assert [(x.method, x.url.path) for x in seen] == [
        ("POST", "/v3/monitors"), ("GET", "/v3/monitors/42"),
        ("PATCH", "/v3/monitors/42"), ("DELETE", "/v3/monitors/42"),
    ]
    assert json.loads(seen[0].content)["url"] == "https://example.com"
    assert json.loads(seen[2].content) == {"friendlyName": "Updated"}


@pytest.mark.asyncio
async def test_pause_uses_empty_json_body_and_rate_limit_is_actionable(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/pause"):
            return httpx.Response(200, json={"id": 42, "status": "PAUSED"})
        return httpx.Response(429, json={"message": "Rate limit exceeded"}, headers={"Retry-After": "30"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.uptimerobot_node.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    paused = await _node("pause_monitor", id="42").execute({})
    assert paused["status"] == "success"
    assert seen[0].headers["Content-Type"].startswith("application/json")
    assert json.loads(seen[0].content) == {}
    limited = await _node("list_monitors").execute({})
    assert limited["status"] == "error"
    assert limited["status_code"] == 429
    assert limited["retry_after"] == "30"
    assert "test-main-key" not in str(limited)


@pytest.mark.asyncio
async def test_status_page_text_fields_use_multipart(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(201, json={"id": 1})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.uptimerobot_node.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await _node("create_status_page", body_friendlyName="NoClick QA").execute({})
    assert result["status"] == "success"
    assert seen[0].headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'NoClick QA' in seen[0].content
