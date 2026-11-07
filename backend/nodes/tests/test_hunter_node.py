"""Hunter API contracts. HTTP responses here are mocked, not live UI evidence."""

from contextlib import asynccontextmanager
from unittest.mock import Mock, patch
from urllib.parse import quote

import httpx
import pytest

from nodes.hunter_node import (
    API_BASE, OPERATIONS, HunterApiKeyCredential, HunterNode, HunterNodeConfig,
)


def sample_value(kind):
    if kind == "boolean":
        return True
    if kind == "integer":
        return 2
    if kind == "number":
        return 1.25
    if kind == "array":
        return '["example"]'
    if kind == "object":
        return '{"value":"example"}'
    return "example"


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
    return values


def node(operation, **values):
    config = HunterNodeConfig(
        config={"operation": operation, **values},
        credentials=HunterApiKeyCredential(api_key="test-key"),
    )
    return HunterNode(node_id="hunter-test", node_type="automation-hunter", node_data={},
                      config=config, sio=Mock(), sid="sid", workflow_id="wf", user_id="user")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(OPERATIONS))
async def test_every_official_operation_uses_documented_method_and_path(operation):
    spec = OPERATIONS[operation]
    calls = []

    class Client:
        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return httpx.Response(200, json={"data": {"id": "ok"}})

    @asynccontextmanager
    async def client_factory(**kwargs):
        yield Client()

    with patch("nodes.hunter_node.guarded_async_client", client_factory):
        result = await node(operation, **required_values(spec)).execute({})
    assert result["status"] == "success"
    assert result["data"]["data"]["id"] == "ok"
    method, url, kwargs = calls[0]
    assert method == spec["method"]
    expected_path = spec["path"]
    for name in spec["path_params"]:
        expected_path = expected_path.replace("{" + name + "}", quote("id/123", safe=""))
    assert url == API_BASE + expected_path
    assert kwargs["headers"]["X-API-KEY"] == "test-key"
    assert "api_key" not in (kwargs["params"] or {})


def test_catalog_matches_distinct_official_method_paths_and_schema():
    assert len(OPERATIONS) == 182
    assert len({(spec["method"], spec["path"]) for spec in OPERATIONS.values()}) == 182
    assert {"search_domain", "find_email", "verify_email", "create_lead", "get_account"} <= OPERATIONS.keys()
    schema = HunterNodeConfig.model_json_schema()
    assert len(schema["$defs"]) == 183
    assert schema["$defs"]["HunterApiKeyCredential"]["properties"]["api_key"]["minLength"] == 1


@pytest.mark.asyncio
async def test_create_lead_sends_json_body_without_key_in_query():
    captured = {}

    class Client:
        async def request(self, method, url, **kwargs):
            captured.update(kwargs)
            return httpx.Response(201, json={"data": {"id": 17}})

    @asynccontextmanager
    async def client_factory(**kwargs):
        yield Client()

    with patch("nodes.hunter_node.guarded_async_client", client_factory):
        result = await node("create_lead", body_email="hello@example.com", body_json='{"first_name":"Ada"}').execute({})
    assert result["status"] == "success"
    assert captured["json"] == {"email": "hello@example.com", "first_name": "Ada"}
    assert captured["params"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "values", "expected_path", "expected_query"),
    [
        ("search_domain", {"query_domain": "example.com", "query_limit": 2},
         "/domain-search", {"domain": "example.com", "limit": 2}),
        ("find_email", {"query_domain": "example.com", "query_first_name": "Ada",
                        "query_last_name": "Lovelace"},
         "/email-finder", {"domain": "example.com", "first_name": "Ada", "last_name": "Lovelace"}),
        ("verify_email", {"query_email": "ada@example.com"},
         "/email-verifier", {"email": "ada@example.com"}),
    ],
)
async def test_common_lookup_operations_send_expected_query(operation, values, expected_path, expected_query):
    captured = {}

    class Client:
        async def request(self, method, url, **kwargs):
            captured.update(method=method, url=url, **kwargs)
            return httpx.Response(200, json={"data": {"status": "valid"}})

    @asynccontextmanager
    async def client_factory(**kwargs):
        yield Client()

    with patch("nodes.hunter_node.guarded_async_client", client_factory):
        result = await node(operation, **values).execute({})
    assert result["status"] == "success"
    assert captured["method"] == "GET"
    assert captured["url"] == API_BASE + expected_path
    assert captured["params"] == expected_query
    assert captured["headers"]["X-API-KEY"] == "test-key"


@pytest.mark.asyncio
async def test_bulk_upsert_parses_leads_array_into_json_body():
    captured = {}

    class Client:
        async def request(self, method, url, **kwargs):
            captured.update(kwargs)
            return httpx.Response(200, json={"data": [{"status": "success"}]})

    @asynccontextmanager
    async def client_factory(**kwargs):
        yield Client()

    with patch("nodes.hunter_node.guarded_async_client", client_factory):
        result = await node("bulk_upsert_leads", body_leads='[{"email":"ada@example.com"}]').execute({})
    assert result["status"] == "success"
    assert captured["json"] == {"leads": [{"email": "ada@example.com"}]}


@pytest.mark.asyncio
async def test_rate_limit_is_structured_and_write_is_not_retried():
    calls = 0

    class Client:
        async def request(self, method, url, **kwargs):
            nonlocal calls
            calls += 1
            return httpx.Response(429, json={"errors": [{"id": "limit"}]}, headers={"Retry-After": "3"})

    @asynccontextmanager
    async def client_factory(**kwargs):
        yield Client()

    with patch("nodes.hunter_node.guarded_async_client", client_factory):
        result = await node("create_lead", body_email="hello@example.com").execute({})
    assert calls == 1
    assert result["status"] == "error"
    assert result["retry_after"] == "3"


@pytest.mark.asyncio
async def test_no_content_delete_returns_success():
    class Client:
        async def request(self, method, url, **kwargs):
            return httpx.Response(204)

    @asynccontextmanager
    async def client_factory(**kwargs):
        yield Client()

    with patch("nodes.hunter_node.guarded_async_client", client_factory):
        result = await node("delete_lead", path_id="17").execute({})
    assert result["status"] == "success"
    assert result["data"] == {"success": True}


@pytest.mark.asyncio
async def test_invalid_json_and_query_api_key_fail_before_request():
    with pytest.raises(ValueError, match="valid JSON"):
        await node("create_lead", body_email="hello@example.com", body_json="{").execute({})
    with pytest.raises(ValueError, match="without api_key"):
        await node("get_account", query_json='{"api_key":"other"}').execute({})
