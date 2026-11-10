"""Contract and HTTP transport tests for the ngrok API-key node.

The transport is local and deterministic. These tests do not represent a live
ngrok credential connection or a successful FlowCanvas run.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import ngrok_node
from nodes.ngrok_node import NgrokNode, NgrokNodeConfig, OPERATIONS, POLL_TRIGGERS


def _node(operation: str, **fields: object) -> NgrokNode:
    config = NgrokNodeConfig.model_validate({
        "config": {"operation": operation, **fields},
        "credentials": {"api_key": "example-secret-api-key"},
    })
    return NgrokNode(
        node_id="ngrok-test", node_type="automation-ngrok", node_data={},
        config=config, sio=Mock(), sid="sid", workflow_id="workflow",
        user_id="user",
    )


def _transport(monkeypatch: pytest.MonkeyPatch, handler):
    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(ngrok_node.httpx, "AsyncClient", client)


def test_catalog_and_schema_cover_all_official_operations():
    assert len(OPERATIONS) == 251
    assert len({(item["method"], item["path"]) for item in OPERATIONS.values()}) == 251
    assert all(item["path"].startswith("/") for item in OPERATIONS.values())
    schema = NgrokNode.get_config_schema()
    operation_ids = {
        value["properties"]["operation"]["const"]
        for value in schema["$defs"].values()
        if isinstance(value, dict)
        and "operation" in value.get("properties", {})
    }
    assert operation_ids == set(OPERATIONS) | set(POLL_TRIGGERS)
    assert schema["$defs"]["NgrokAPIKeyCredential"]["properties"]["api_key"]["ui:widget"] == "password"
    assert schema["$defs"]["NgrokSecretsCreateConfig"]["properties"]["body_value"]["ui:widget"] == "password"


def test_required_fields_are_validated_before_any_request():
    with pytest.raises(ValidationError):
        _node("create_endpoints", body_url="https://example.ngrok.app")
    with pytest.raises(ValidationError):
        _node("get_endpoints")


@pytest.mark.asyncio
async def test_list_uses_fixed_host_bearer_key_version_and_query(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json={"endpoints": [{"id": "ep_1"}]})

    _transport(monkeypatch, handler)
    result = await _node("list_endpoints", limit="2", filter='type == "cloud"').execute({})
    assert result == {
        "operation": "list_endpoints", "status": "success", "status_code": 200,
        "data": {"endpoints": [{"id": "ep_1"}]},
    }
    request = seen[0]
    assert request.method == "GET"
    assert str(request.url).startswith("https://api.ngrok.com/endpoints?")
    assert request.url.params["limit"] == "2"
    assert request.url.params["filter"] == 'type == "cloud"'
    assert request.headers["authorization"] == "Bearer example-secret-api-key"
    assert request.headers["ngrok-version"] == "2"


@pytest.mark.asyncio
async def test_create_sends_typed_body_and_extra_fields(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(201, json={"id": "ep_new"})

    _transport(monkeypatch, handler)
    result = await _node(
        "create_endpoints", body_url="https://demo.ngrok.app",
        body_type="cloud", body_traffic_policy='{"on_http_request":[]}',
        body_pooling_enabled=False, extra_body={"metadata": '{"team":"infra"}'},
    ).execute({})
    assert result["status"] == "success"
    assert result["data"]["id"] == "ep_new"
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/endpoints"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["authorization"] == "Bearer example-secret-api-key"
    assert json.loads(request.read()) == {
        "url": "https://demo.ngrok.app", "type": "cloud",
        "traffic_policy": '{"on_http_request":[]}', "pooling_enabled": False,
        "metadata": '{"team":"infra"}',
    }


@pytest.mark.asyncio
async def test_update_sends_patch_with_encoded_id(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json={"id": "ep/1", "description": "Updated"})

    _transport(monkeypatch, handler)
    result = await _node("update_endpoints", id="ep/1", body_description="Updated").execute({})
    assert result["status"] == "success"
    assert seen[0].method == "PATCH"
    assert seen[0].url.raw_path == b"/endpoints/ep%2F1"
    assert json.loads(seen[0].read()) == {"description": "Updated"}


@pytest.mark.asyncio
async def test_get_quotes_path_and_delete_handles_empty_body(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"id": "ep/a"})

    _transport(monkeypatch, handler)
    got = await _node("get_endpoints", id="ep/a").execute({})
    deleted = await _node("delete_endpoints", id="ep/a").execute({})
    assert got["data"]["id"] == "ep/a"
    assert deleted["status_code"] == 204
    assert deleted["data"] == {"success": True}
    assert all(request.url.raw_path == b"/endpoints/ep%2Fa" for request in seen)


@pytest.mark.asyncio
async def test_api_rejection_is_error_without_exposing_key(monkeypatch):
    def handler(request: httpx.Request):
        return httpx.Response(403, json={"msg": "permission denied", "error_code": "ERR_NGROK_42"})

    _transport(monkeypatch, handler)
    result = await _node("list_endpoints").execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 403
    assert result["error"] == "permission denied"
    assert result["error_code"] == "ERR_NGROK_42"
    assert "example-secret-api-key" not in str(result)


@pytest.mark.asyncio
async def test_timeout_and_missing_credential(monkeypatch):
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("timed out", request=request)

    _transport(monkeypatch, handler)
    result = await _node("list_endpoints").execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 408

    config = NgrokNodeConfig.model_validate({"config": {"operation": "list_endpoints"}})
    node = NgrokNode(
        node_id="ngrok-test", node_type="automation-ngrok", node_data={}, config=config,
    )
    with pytest.raises(ValueError, match="API key credential"):
        await node.execute({})


# Contracts from the current ngrok AI Gateway documentation. The legacy core
# OpenAPI catalog does not include this separately hosted control-plane API.
@pytest.mark.parametrize("resource,path", [
    ("ai_gateway_api_keys", "/api-keys"),
    ("ai_gateway_provider_keys", "/provider-keys"),
])
@pytest.mark.parametrize("action,method", [
    ("list", "GET"), ("create", "POST"), ("get", "GET"),
    ("update", "PATCH"), ("delete", "DELETE"),
])
@pytest.mark.asyncio
async def test_current_ai_gateway_request_contract(monkeypatch, resource, path, action, method):
    """Assert documented requests without fabricating a successful API response."""
    fields = {}
    if action in {"get", "update", "delete"}:
        fields["id"] = "1"
        path += "/1"
    if action == "list":
        fields.update(beforeId="1", limit=100)
        if resource == "ai_gateway_provider_keys":
            fields["provider"] = "openai"
    if action == "create" and resource == "ai_gateway_provider_keys":
        fields.update(body_providerId="openai", body_name="openai", body_value="<token>")
    if action == "update":
        fields["body_description"] = None  # Explicit null clears a nullable field.
    seen = []

    def handler(request):
        seen.append(request)
        raise httpx.ReadTimeout("Request recorded; no fabricated API response", request=request)

    _transport(monkeypatch, handler)
    result = await _node(f"{action}_{resource}", **fields).execute({})
    assert result["status_code"] == 408
    assert len(seen) == 1
    request = seen[0]
    assert request.method == method
    assert request.url.host == "api.ngrok.ai"
    assert request.url.path == path
    assert request.headers["authorization"] == "Bearer example-secret-api-key"
    assert "ngrok-version" not in request.headers
    if action == "list":
        assert dict(request.url.params) == {
            "beforeId": "1", "limit": "100",
            **({"provider": "openai"} if resource == "ai_gateway_provider_keys" else {}),
        }
    elif action in {"create", "update"}:
        expected = {key.removeprefix("body_"): value for key, value in fields.items() if key.startswith("body_")}
        assert json.loads(request.read()) == expected


def test_ai_gateway_requires_current_fields_and_rejects_obsolete_fields():
    with pytest.raises(ValidationError):
        _node("create_ai_gateway_provider_keys", body_value="<token>")
    for limit in (0, 101):
        with pytest.raises(ValidationError):
            _node("list_ai_gateway_api_keys", limit=limit)
    with pytest.raises(ValidationError):
        _node("list_ai_gateway_api_keys", before_id="1")
    with pytest.raises(ValidationError):
        _node("list_ai_gateway_provider_keys", ai_gateway_api_key_id="1")
    with pytest.raises(ValidationError):
        _node("create_ai_gateway_api_keys", extra_body={"obsolete_field": True})
    schema = NgrokNode.get_config_schema()
    assert schema["$defs"]["NgrokAiGatewayProviderKeysCreateConfig"]["properties"]["body_value"]["ui:widget"] == "password"


# Resource rows are copied from ngrok's docs and its official Python SDK tests.
# Pagination scenarios use the terminal null described at https://ngrok.com/docs/api#pagination.
def _documented_page(key):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "ngrok" / f"{key}.json").read_text())
    page = deepcopy(fixture["body"])
    page["next_page_uri"] = None
    return page


def _persist_poll_state(node):
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        replacement, result = mutator(deepcopy(state))
        if replacement is not None:
            state = replacement
        return result

    node._update_node_state = update
    return lambda: deepcopy(state)


@pytest.mark.parametrize("operation", POLL_TRIGGERS)
@pytest.mark.asyncio
async def test_poll_baseline_new_items_dedup_and_agent_event(monkeypatch, operation):
    path, key, _ = POLL_TRIGGERS[operation]
    documented = _documented_page(key)
    page = {key: [], "next_page_uri": None}
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=page)

    _transport(monkeypatch, handler)
    node = _node(operation)
    state = _persist_poll_state(node)
    baseline = await node.execute({})
    assert baseline["new_item_count"] == 0
    assert not NgrokNode.should_propagate_output(baseline, {"operation": operation})
    assert NgrokNode.resolve_agent_event(baseline) is None
    page = documented
    fresh = await node.execute({})
    assert fresh[key] == documented[key]
    assert fresh["new_item_count"] == len(documented[key])
    assert NgrokNode.should_propagate_output(fresh, {"operation": operation})
    event = NgrokNode.resolve_agent_event(fresh)
    assert "ngrok" in event["text"]
    assert all(item["id"] in event["text"] for item in documented[key])
    assert (await node.execute({}))["new_item_count"] == 0
    assert state()["seen_ids"] == [item["id"] for item in documented[key]]
    assert all(request.url.path == path for request in seen)
    assert all(request.url.params["limit"] == "100" for request in seen)


@pytest.mark.asyncio
async def test_poll_pagination_preserves_filter_and_rebaselines_changed_scope(monkeypatch):
    page = _documented_page("reserved_domains")
    first, second, third = page["reserved_domains"]
    seen = []

    def handler(request):
        seen.append(request)
        if "before_id" not in request.url.params:
            return httpx.Response(200, json={"reserved_domains": [first], "next_page_uri":
                f"https://api.ngrok.com/reserved_domains?limit=100&before_id={first['id']}"})
        assert request.url.params["before_id"] == first["id"]
        return httpx.Response(200, json={"reserved_domains": [second, third], "next_page_uri": None})

    _transport(monkeypatch, handler)
    node = _node("on_new_reserved_domain", filter='obj.domain.startsWith("myapi.ngrok")')
    state = _persist_poll_state(node)
    assert (await node.execute({}))["new_item_count"] == 0
    assert len(state()["seen_ids"]) == 3
    assert all(request.url.params["filter"] == 'obj.domain.startsWith("myapi.ngrok")' for request in seen)
    node.config.config.filter = None
    assert (await node.execute({}))["new_item_count"] == 0


@pytest.mark.parametrize("uri", ["https://attacker.example/endpoints?before_id=ep_1",
                                 "https://api.ngrok.com/api_keys?before_id=ep_1",
                                 "https://api.ngrok.com/endpoints?before_id=ep_1"])
@pytest.mark.asyncio
async def test_poll_refuses_invalid_or_repeated_pagination_before_writing_state(monkeypatch, uri):
    page = _documented_page("endpoints")
    page["next_page_uri"] = uri
    _transport(monkeypatch, lambda request: httpx.Response(200, json=page))
    node = _node("on_new_endpoint")
    state = _persist_poll_state(node)
    with pytest.raises(ValueError, match="invalid or repeated"):
        await node.execute({})
    assert state() == {}


@pytest.mark.asyncio
async def test_poll_failure_does_not_establish_baseline(monkeypatch):
    _transport(monkeypatch, lambda request: httpx.Response(401, json={"msg": "invalid key"}))
    node = _node("on_new_endpoint")
    state = _persist_poll_state(node)
    result = await node.execute({})
    assert result["status"] == "error"
    assert state() == {}


@pytest.mark.parametrize("operation,fields", [
    ("create_event_subscriptions", {"body_sources": ["not-an-object"]}),
    ("update_event_subscriptions", {"id": "<string>", "body_sources": ["not-an-object"]}),
    ("create_reserved_domains", {"body_resolves_to": ["not-an-object"]}),
    ("update_reserved_domains", {"id": "<string>", "body_resolves_to": ["not-an-object"]}),
])
def test_nested_resource_arrays_require_objects(operation, fields):
    with pytest.raises(ValidationError):
        _node(operation, **fields)
