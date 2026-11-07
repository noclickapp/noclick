"""PayPal token, endpoint, and credential contracts."""

from __future__ import annotations

import json
import re
from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.core.binary_output import BinaryOutput
from nodes.paypal_node import BY_NAME, OPERATIONS, PayPalNode, PayPalNodeConfig, _TOKEN_CACHE


def _node(action: dict, *, environment: str = "sandbox") -> PayPalNode:
    config = PayPalNodeConfig.model_validate({
        "config": action,
        "credentials": {"client_id": "test-client", "client_secret": "test-secret",
                        "environment": environment},
    })
    return PayPalNode(
        node_id="paypal-test", node_type="automation-paypal", node_data={},
        config=config, sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


def _action(spec) -> dict:
    action = {"operation": spec.name}
    for key in re.findall(r"\{([a-z_]+)\}", spec.path):
        action[key] = "sample-id"
    if spec.method == "PATCH":
        action["body_json"] = '[{"op":"replace","path":"/description","value":"Updated"}]'
    elif spec.body:
        action["body_json"] = '{"name":"Example"}'
    return action


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", OPERATIONS, ids=lambda op: op.name)
async def test_every_operation_uses_current_paypal_route(spec):
    _TOKEN_CACHE.clear()
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "access-123", "expires_in": 3600})
        return httpx.Response(200, json={"items": [{"id": "sample-id"}]})

    real_client = httpx.AsyncClient
    with patch("nodes.paypal_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await _node(_action(spec)).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 2
    token_request, api_request = requests
    assert token_request.url.host == "api-m.sandbox.paypal.com"
    assert token_request.url.path == "/v1/oauth2/token"
    assert token_request.headers["authorization"].startswith("Basic ")
    assert b"grant_type=client_credentials" in token_request.content
    assert api_request.method == spec.method
    assert api_request.url.path == re.sub(r"\{[a-z_]+\}", "sample-id", spec.path)
    assert api_request.headers["authorization"] == "Bearer access-123"
    assert "test-secret" not in str(api_request.url)
    if spec.method == "PATCH":
        assert isinstance(json.loads(api_request.content), list)


@pytest.mark.asyncio
async def test_live_environment_and_idempotency_key():
    _TOKEN_CACHE.clear()
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "live-token", "expires_in": 3600})
        return httpx.Response(201, json={"id": "order-1"})

    real_client = httpx.AsyncClient
    with patch("nodes.paypal_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await _node({"operation": "create_order", "body_json": '{"intent":"CAPTURE"}',
                              "request_id": "fixed-retry-key"}, environment="live").execute({})
    assert result["status"] == "success"
    assert all(request.url.host == "api-m.paypal.com" for request in requests)
    assert requests[1].headers["paypal-request-id"] == "fixed-retry-key"


@pytest.mark.asyncio
async def test_token_is_cached_without_secret_in_cache_key():
    _TOKEN_CACHE.clear()
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(200, json={"products": []})

    real_client = httpx.AsyncClient
    with patch("nodes.paypal_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        await _node({"operation": "list_products"}).execute({})
        await _node({"operation": "list_products"}).execute({})
    assert [request.url.path for request in requests].count("/v1/oauth2/token") == 1
    assert all("test-secret" not in key for key in _TOKEN_CACHE.keys())


@pytest.mark.asyncio
async def test_rejects_path_injection_and_invalid_json_before_request():
    for action in ({"operation": "get_product", "product_id": "../private"},
                   {"operation": "list_products", "query_json": "[]"},
                   {"operation": "update_order", "order_id": "valid", "body_json": "{}"}):
        result = await _node(action).execute({})
        assert result["status"] == "error"


@pytest.mark.asyncio
async def test_invoice_qr_code_preserves_image_response():
    _TOKEN_CACHE.clear()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(200, content=b"PNG data", headers={"content-type": "image/png"})

    real_client = httpx.AsyncClient
    with patch("nodes.paypal_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await _node({"operation": "generate_invoice_qr_code", "invoice_id": "INV-1"}).execute({})
    assert result["status"] == "success"
    assert result["data"] == BinaryOutput(
        data=b"PNG data", content_type="image/png", filename="paypal-qr-code.png")


def test_schema_credential_metadata_and_catalog():
    assert len(OPERATIONS) == len(BY_NAME) == 113
    schema = PayPalNode.get_config_schema()
    assert schema["$defs"]["PayPalClientCredential"]["x-credential-type"] == "api_key"
    assert "x-oauth-provider" not in schema["$defs"]["PayPalClientCredential"]
    assert PayPalNode.connection_evidence.operation == "list_products"
