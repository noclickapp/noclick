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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["provide_dispute_evidence", "appeal_dispute"])
async def test_dispute_evidence_uses_documented_multipart_input(operation):
    # PayPal Use Disputes API guide: tracking/notes are the JSON input part.
    # https://developer.paypal.com/platforms/disputes/handle-disputes/use-disputes-api/
    _TOKEN_CACHE.clear()
    evidence = {"evidences": [{"evidence_type": "PROOF_OF_FULFILLMENT",
        "evidence_info": {"tracking_info": [{"carrier_name": "FEDEX", "tracking_number": "122533485"}]},
        "notes": "Test"}]}
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(200)

    real_client = httpx.AsyncClient
    with patch("nodes.paypal_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await _node({"operation": operation, "dispute_id": "PP-D-27803",
                              "body_json": json.dumps(evidence)}).execute({})
    assert result["status"] == "success"
    request = requests[-1]
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    from email.parser import BytesParser
    from email.policy import default
    message = BytesParser(policy=default).parsebytes(
        ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode() + request.content)
    parts = list(message.iter_parts())
    assert len(parts) == 1
    assert parts[0].get_param("name", header="content-disposition") == "input"
    assert parts[0].get_content_type() == "application/json"
    assert json.loads(parts[0].get_payload(decode=True)) == evidence


def test_paypal_scope_metadata_uses_seller_dispute_and_webhook_requirements():
    scopes = PayPalNode.scope_registry
    assert scopes.require("provide_dispute_evidence").scopes == (
        "https://uri.paypal.com/services/disputes/update-seller",)
    assert scopes.require("on_event").scopes == (
        "https://uri.paypal.com/services/applications/webhooks",)
    assert scopes.require("refund_capture").scopes == (
        "https://uri.paypal.com/services/payments/refund",)
