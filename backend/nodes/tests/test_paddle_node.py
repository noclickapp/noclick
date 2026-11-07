"""Paddle Billing request contracts for every action in the pinned OpenAPI spec."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.paddle_node import (
    CONFIG_MODELS,
    OPERATIONS,
    PaddleNode,
    PaddleNodeConfig,
    _field_name,
    _catalog,
)


def _action(op: dict) -> dict:
    values = {"operation": op["name"]}
    for param in op["path_params"]:
        values[_field_name("path", param["name"])] = "sample-id"
    for param in op["query_params"]:
        if param["required"]:
            values[_field_name("query", param["name"])] = "sample-value"
    for param in op["header_params"]:
        if param["required"]:
            values[_field_name("header", param["name"])] = "true"
    if op["body_supported"] and op["body_required"]:
        values["body_json"] = json.dumps(
            {name: "sample-value" for name in op["body_required_keys"]}
        )
    return values


def _node(action: dict, environment: str = "sandbox", key: str = "test-api-key") -> PaddleNode:
    config = PaddleNodeConfig.model_validate(
        {
            "config": action,
            "credentials": {
                "credential_type": "paddle_api_key",
                "environment": environment,
                "api_key": key,
            },
        }
    )
    return PaddleNode(
        node_id="paddle-test",
        node_type="automation-paddle",
        node_data={},
        config=config,
        sio=Mock(),
        sid="sid",
        workflow_id="workflow",
        user_id="user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("op", OPERATIONS.values(), ids=lambda op: op["name"])
async def test_every_action_uses_documented_method_path_and_auth(op):
    captured = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [{"id": "ok"}], "meta": {"has_more": False}})

    real_client = httpx.AsyncClient
    with patch(
        "nodes.paddle_node.httpx.AsyncClient",
        side_effect=lambda **kw: real_client(
            transport=httpx.MockTransport(respond), **kw
        ),
    ):
        result = await _node(_action(op)).execute({})
    request = captured[0]
    expected_path = re.sub(r"\{[^{}]+\}", "sample-id", op["path"])
    assert request.method == op["method"]
    assert request.url.host == "sandbox-api.paddle.com"
    assert request.url.path == expected_path
    assert request.headers["Authorization"] == "Bearer test-api-key"
    assert request.headers["Paddle-Version"] == "1"
    for param in op["query_params"]:
        if param["required"]:
            assert request.url.params[param["name"]] == "sample-value"
    if op["body_supported"] and op["body_required"]:
        assert json.loads(request.content) == json.loads(_action(op)["body_json"])
    assert result["data"] == [{"id": "ok"}]
    assert result["meta"] == {"has_more": False}
    assert result["timing_ms"]["api_request"] >= 0


def test_catalog_schema_and_permission_metadata_match():
    root = Path(__file__).resolve().parents[2]
    catalog = _catalog
    schema = json.loads(
        (root.parent / "frontend" / "app" / "schemas" / "nodes" / "paddle.json").read_text()
    )
    assert len(catalog["operations"]) == len(OPERATIONS) == len(CONFIG_MODELS) == 99
    assert "540ea17369325ff866b65ecf6c5105592f16fb5d" in catalog["source"]
    assert all(op["docs_url"].startswith("https://developer.paddle.com/") for op in OPERATIONS.values())
    schema_actions = {
        entry["properties"]["operation"]["const"]
        for entry in schema["$defs"].values()
        if isinstance(entry, dict) and "operation" in entry.get("properties", {})
    }
    assert schema_actions == set(OPERATIONS)


@pytest.mark.asyncio
async def test_environment_binding_and_path_escaping():
    with pytest.raises(ValueError, match="Live Paddle API keys require the live environment"):
        await _node({"operation": "list_event_types"}, key="pdl_live_test").execute({})
    with pytest.raises(ValueError, match="Sandbox Paddle API keys require the sandbox environment"):
        await _node(
            {"operation": "list_event_types"}, environment="live", key="pdl_sdbx_test"
        ).execute({})
    captured = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": {"id": "ok"}})

    real_client = httpx.AsyncClient
    with patch(
        "nodes.paddle_node.httpx.AsyncClient",
        side_effect=lambda **kw: real_client(
            transport=httpx.MockTransport(respond), **kw
        ),
    ):
        await _node(
            {"operation": "get_product", "path_product_id": "a/b"},
            environment="live",
        ).execute({})
    assert captured[0].url.host == "api.paddle.com"
    assert "%2F" in str(captured[0].url)


@pytest.mark.asyncio
async def test_required_body_validation_and_api_error_redact_key():
    with pytest.raises(ValueError, match="missing required keys: email"):
        await _node({"operation": "create_customer", "body_json": "{}"}).execute({})
    with pytest.raises(ValueError, match="valid JSON"):
        await _node({"operation": "create_customer", "body_json": "{"}).execute({})

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": "insufficient_permissions",
                    "detail": "No access for private-test-key",
                }
            },
        )

    real_client = httpx.AsyncClient
    with patch(
        "nodes.paddle_node.httpx.AsyncClient",
        side_effect=lambda **kw: real_client(
            transport=httpx.MockTransport(respond), **kw
        ),
    ):
        with pytest.raises(ValueError, match="insufficient_permissions") as exc:
            await _node({"operation": "list_event_types"}, key="private-test-key").execute({})
    assert "private-test-key" not in str(exc.value)


@pytest.mark.asyncio
async def test_query_and_headers_preserve_documented_names():
    op = OPERATIONS["list_customers"]
    action = _action(op)
    action["query_per_page"] = "25"
    if op["header_params"]:
        action[_field_name("header", op["header_params"][0]["name"])] = "true"
    captured = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": []})

    real_client = httpx.AsyncClient
    with patch(
        "nodes.paddle_node.httpx.AsyncClient",
        side_effect=lambda **kw: real_client(
            transport=httpx.MockTransport(respond), **kw
        ),
    ):
        await _node(action).execute({})
    assert captured[0].url.params["per_page"] == "25"
    if op["header_params"]:
        assert captured[0].headers[op["header_params"][0]["name"]] == "true"
