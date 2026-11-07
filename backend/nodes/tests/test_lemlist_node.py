"""Lemlist API contracts. All HTTP responses are mocked; live UI testing is separate."""

import base64
from contextlib import asynccontextmanager
from unittest.mock import Mock, patch
from urllib.parse import quote

import httpx
import pytest

from nodes.lemlist_node import (
    API_BASE, OPERATIONS, LemlistApiKeyCredential, LemlistNode, LemlistNodeConfig,
)


def required_values(spec):
    values = {f"path_{name}": "id/123" for name in spec["path_params"]}
    for param in spec["query_params"]:
        if param["required"]:
            values[f"query_{param['name']}"] = sample_value(param["type"])
    for prop in spec["body_properties"]:
        if prop["required"]:
            values[f"body_{prop['name']}"] = sample_value(prop["type"])
    if spec["body_required"] and not any(key.startswith("body_") for key in values):
        values["body_json"] = "{}"
    if spec["body_content_type"] == "multipart/form-data":
        values["file_base64"] = base64.b64encode(b"audio bytes").decode()
    return values


def sample_value(kind):
    if kind == "boolean":
        return True
    if kind == "integer":
        return 2
    if kind == "number":
        return 1.25
    if kind == "array":
        return '["value"]'
    if kind == "object":
        return '{"value":"example"}'
    return "example"


def node(operation, **values):
    config = LemlistNodeConfig(
        config={"operation": operation, **values},
        credentials=LemlistApiKeyCredential(api_key="test-key"),
    )
    return LemlistNode(node_id="lemlist-test", node_type="automation-lemlist", node_data={},
                       config=config, sio=Mock(), sid="sid", workflow_id="wf", user_id="user")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(OPERATIONS))
async def test_every_documented_operation_uses_its_method_path_and_required_inputs(operation):
    spec = OPERATIONS[operation]
    calls = []

    class Client:
        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return httpx.Response(200, json={"items": [{"id": "ok"}]})

    @asynccontextmanager
    async def client_factory(**kwargs):
        yield Client()

    with patch("nodes.lemlist_node.guarded_async_client", client_factory):
        result = await node(operation, **required_values(spec)).execute({})
    assert result["status"] == "success"
    assert result["data"]["items"][0]["id"] == "ok"
    method, url, kwargs = calls[0]
    assert method == spec["method"]
    expected_path = spec["path"]
    for name in spec["path_params"]:
        expected_path = expected_path.replace("{" + name + "}", quote("id/123", safe=""))
    assert url == API_BASE + expected_path
    auth_request = next(kwargs["auth"].auth_flow(httpx.Request(method, url)))
    assert auth_request.headers["Authorization"] == (
        "Basic " + base64.b64encode(b":test-key").decode()
    )
    if spec["body_content_type"] == "multipart/form-data":
        assert kwargs["files"]["file"][1] == b"audio bytes"


def test_catalog_has_one_operation_per_documented_method_and_path():
    assert len(OPERATIONS) == 176
    assert len({(spec["method"], spec["path"]) for spec in OPERATIONS.values()}) == 176
    assert {"create_campaign", "create_lead_in_campaign", "get_team"} <= OPERATIONS.keys()
    schema = LemlistNodeConfig.model_json_schema()
    assert len(schema["$defs"]) == 177
    assert schema["$defs"]["LemlistApiKeyCredential"]["properties"]["api_key"]["minLength"] == 1


@pytest.mark.asyncio
async def test_create_campaign_builds_explicit_body_and_json_extra():
    captured = {}

    class Client:
        async def request(self, method, url, **kwargs):
            captured.update(kwargs)
            return httpx.Response(201, json={"_id": "campaign-1"})

    @asynccontextmanager
    async def client_factory(**kwargs):
        yield Client()

    with patch("nodes.lemlist_node.guarded_async_client", client_factory):
        result = await node("create_campaign", body_name="Welcome",
                            body_autoReview=True, body_json='{"timezone":"Europe/Paris"}').execute({})
    assert result["status"] == "success"
    assert captured["json"] == {"name": "Welcome", "autoReview": True, "timezone": "Europe/Paris"}


@pytest.mark.asyncio
async def test_rate_limit_returns_retry_after_without_retrying_write():
    calls = 0

    class Client:
        async def request(self, method, url, **kwargs):
            nonlocal calls
            calls += 1
            return httpx.Response(429, json={"error": "rate_limit"}, headers={"Retry-After": "2"})

    @asynccontextmanager
    async def client_factory(**kwargs):
        yield Client()

    with patch("nodes.lemlist_node.guarded_async_client", client_factory):
        result = await node("create_campaign", body_name="Welcome").execute({})
    assert calls == 1
    assert result["status"] == "error"
    assert result["retry_after"] == "2"


@pytest.mark.asyncio
async def test_invalid_body_json_fails_before_http_request():
    with pytest.raises(ValueError, match="valid JSON"):
        await node("create_campaign", body_name="Welcome", body_json="{").execute({})
