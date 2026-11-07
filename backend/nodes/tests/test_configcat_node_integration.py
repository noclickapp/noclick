"""ConfigCat routing, credential handling, and response contract tests."""

import base64
import json
import re
from urllib.parse import quote

import httpx
import pytest

from nodes.configcat_node import (
    API_BASE,
    OPERATIONS,
    ConfigCatNode,
    ConfigCatNodeConfig,
    _path_field,
)


def _node(operation: str, **values):
    config = ConfigCatNodeConfig.model_validate(
        {
            "config": {"operation": operation, **values},
            "credentials": {"username": "qa-user", "password": "qa-secret"},
        }
    )
    return ConfigCatNode("test", "automation-configcat", {}, config=config)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_official_operation_routes_send_authenticated_requests(
    monkeypatch, operation
):
    """Each documented route is reachable through its generated config model."""
    spec = OPERATIONS[operation]
    values = {
        _path_field(variable): "qa value"
        for variable in re.findall(r"\{([^}]+)\}", spec["path"])
    }
    if spec["body"]:
        values["body_json"] = "[]" if spec["method"] == "PATCH" else '{"name":"QA"}'
    node = _node(operation, **values)
    expected_path = spec["path"]
    for variable in re.findall(r"\{([^}]+)\}", expected_path):
        expected_path = expected_path.replace(
            "{" + variable + "}", quote("qa value", safe="")
        )
    seen = []

    def handle(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json={"route": operation})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.configcat_node.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = await node.execute({})
    assert len(seen) == 1
    request = seen[0]
    assert request.method == spec["method"]
    assert str(request.url) == API_BASE + expected_path
    assert (
        base64.b64decode(request.headers["Authorization"].removeprefix("Basic "))
        == b"qa-user:qa-secret"
    )
    if spec["body"]:
        assert json.loads(request.content) == json.loads(values["body_json"])
    assert result["status"] == "success"
    assert result["data"] == {"route": operation}
    assert result["timing_ms"]["api_request"] >= 0


def test_catalog_covers_management_api_and_excludes_sdk_key_auth():
    assert len(OPERATIONS) == 118
    assert OPERATIONS["get_products"]["path"] == "/v1/products"
    assert OPERATIONS["create_setting"]["path"] == "/v1/configs/{configId}/settings"
    assert OPERATIONS["replace_setting_value_v2"]["method"] == "PUT"
    assert not any("sdkkey" in name for name in OPERATIONS)
    schema = ConfigCatNode.get_config_schema()
    assert schema["x-agent-tool-provider"]
    assert (
        schema["$defs"]["ConfigCatCredential"]["properties"]["password"]["ui:widget"]
        == "password"
    )
    assert ConfigCatNode.connection_evidence.field == "path_productid"
    for definition in schema["$defs"].values():
        properties = definition.get("properties", {})
        for field in properties.values():
            dependency = field.get("x-dynamic-options", {}).get("depends_on")
            assert not dependency or dependency in properties


@pytest.mark.asyncio
async def test_product_picker_proves_credential_and_returns_named_options(monkeypatch):
    def handle(request: httpx.Request):
        assert request.url.path == "/v1/products"
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(
            200, json=[{"productId": "product-1", "name": "NoClick QA"}]
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.configcat_node.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = await ConfigCatNode.load_field_options(
        "path_productid", {"username": "qa-user", "password": "qa-secret"}
    )
    assert result == {"options": [{"label": "NoClick QA", "value": "product-1"}]}


@pytest.mark.asyncio
async def test_jira_connect_uses_documented_route(monkeypatch):
    # The pinned Public Management API contract capitalizes Connect.
    def handle(request: httpx.Request):
        assert request.method == "POST"
        assert request.url.path == "/v1/jira/Connect"
        return httpx.Response(200)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.configcat_node.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = await _node("jira_connect").execute({})
    assert result["status_code"] == 200
    assert result["data"] == {"ok": True}


@pytest.mark.asyncio
async def test_config_picker_discovers_configs_when_operation_has_no_product_field(
    monkeypatch,
):
    paths = []

    def handle(request: httpx.Request):
        paths.append(request.url.path)
        if request.url.path == "/v1/products":
            return httpx.Response(200, json=[{"productId": "product-1"}])
        if request.url.path == "/v1/products/product-1/configs":
            return httpx.Response(200, json=[{"configId": "config-1", "name": "Main"}])
        return httpx.Response(404)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.configcat_node.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = await ConfigCatNode.load_field_options(
        "path_configid", {"username": "qa-user", "password": "qa-secret"}
    )
    assert result == {"options": [{"label": "Main", "value": "config-1"}]}
    assert paths == ["/v1/products", "/v1/products/product-1/configs"]


@pytest.mark.asyncio
async def test_json_input_and_api_failures_are_explicit(monkeypatch):
    with pytest.raises(ValueError, match="Query parameters must be a JSON object"):
        await _node("get_products", query_json="[]").execute({})
    with pytest.raises(ValueError, match="Request body is required"):
        await _node("create_setting", path_configid="config-1", body_json="").execute(
            {}
        )
    with pytest.raises(ValueError, match="Request body must be valid JSON"):
        await _node("create_setting", path_configid="config-1", body_json="{").execute(
            {}
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.configcat_node.httpx.AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="Invalid API credential")
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ValueError, match="ConfigCat API error 401"):
        await _node("get_products").execute({})
