"""Offline Etsy contract tests, one case per operation plus edge cases.

Source URLs for every response schema and the documented request examples are
in fixtures/etsy/responses.json. The spec contains no literal success examples:
these full response samples are GENERATED FROM THE DOCUMENTED SCHEMAS, not
provider-authored responses or live API captures. Do not relabel them as such.

Contract: https://www.etsy.com/openapi/generated/oas/3.0.0.json
Input examples: https://developers.etsy.com/markdown/tutorials/listings.md
https://developers.etsy.com/markdown/tutorials/shopmanagement.md
https://developers.etsy.com/markdown/tutorials/fulfillment.md
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes.etsy_node import EtsyNode, EtsyNodeConfig, EtsyTokenCredential, OPERATIONS
from nodes.scopes.etsy import ETSY_SCOPES

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/etsy/responses.json").read_text()
)
CREDENTIAL = {
    "credential_type": "etsy_token",
    "api_key": "app-key",
    "shared_secret": "app-secret",
    "access_token": "12345678.user-token",
}


def node(config, credentials=CREDENTIAL):
    return EtsyNode(
        node_id="etsy-test",
        node_type="automation-etsy",
        node_data={},
        config=EtsyNodeConfig(config=config, credentials=credentials),
        sio=Mock(),
        sid="test",
        workflow_id="test",
        user_id="test",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(FIXTURES))
async def test_documented_operation(operation):
    fixture = FIXTURES[operation]
    requests = []

    async def respond(request):
        requests.append(request)
        assert request.method == fixture["method"]
        assert request.url.host == "openapi.etsy.com"
        assert request.url.path == fixture["path"]
        assert request.headers["x-api-key"] == "app-key:app-secret"
        assert request.headers["Authorization"] == "Bearer 12345678.user-token"
        route = OPERATIONS[operation]
        cfg = fixture["config"]
        if route["content_type"] == "application/json":
            assert request.headers["Content-Type"] == "application/json"
            body = json.loads(request.content)
            for key in route["body_fields"]:
                if key in cfg:
                    assert body[key] == cfg[key]
        elif route["content_type"]:
            assert (
                request.headers["Content-Type"] == "application/x-www-form-urlencoded"
            )
            body = parse_qs(request.content.decode())
            for key in route["body_fields"]:
                if key not in cfg:
                    continue
                value = cfg[key]
                expected = (
                    ",".join(str(v) for v in value)
                    if isinstance(value, list)
                    else (str(value).lower() if isinstance(value, bool) else str(value))
                )
                # Numeric fields may be normalized to floats by the config.
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    assert float(body[key][0]) == float(value)
                else:
                    assert body[key] == [expected]
        if operation == "list_orders":
            assert request.url.params["was_paid"] == "true"
            assert request.url.params["was_shipped"] == "false"
        if fixture["status"] == 204:
            return httpx.Response(204)
        return httpx.Response(fixture["status"], json=fixture["body"])

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch("nodes.etsy_node.httpx.AsyncClient", return_value=client):
        result = await node({"operation": operation, **fixture["config"]}).execute({})
    assert len(requests) == 1
    assert result["status"] == "success", result
    assert result["status_code"] == fixture["status"]
    assert result["data"] == (
        {"deleted": True} if fixture["status"] == 204 else fixture["body"]
    )
    assert result["timing_ms"]["api_request"] >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 429, 500])
async def test_preserves_provider_rejection(status):
    # Etsy ErrorSchema: https://www.etsy.com/openapi/generated/oas/3.0.0.json#/components/schemas/ErrorSchema
    text = '{"error":"Unauthorized"}'
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text=text))
    )
    with patch("nodes.etsy_node.httpx.AsyncClient", return_value=client):
        result = await node({"operation": "get_me"}).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == status
    assert result["error"] == text


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, [], {"error": "Unauthorized"}])
async def test_invalid_identity_is_not_connection_proof(payload):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    with patch("nodes.etsy_node.httpx.AsyncClient", return_value=client):
        assert (await node({"operation": "get_me"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_timeout_is_error():
    def timeout(request):
        raise httpx.ReadTimeout("Etsy request timed out", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    with patch("nodes.etsy_node.httpx.AsyncClient", return_value=client):
        assert (await node({"operation": "get_me"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_missing_credentials():
    with pytest.raises(ValueError, match="Connect your Etsy"):
        await node({"operation": "get_me"}, None).execute({})


def test_scope_table_covers_every_operation():
    assert set(ETSY_SCOPES) == set(OPERATIONS)
    assert set(ETSY_SCOPES.declared_scopes()) == {
        "listings_r",
        "listings_w",
        "listings_d",
        "shops_r",
        "shops_w",
        "transactions_r",
        "transactions_w",
    }
    assert EtsyNode.connection_evidence.identity_operation == "get_me"
    assert ETSY_SCOPES.require("get_me").scopes == ("shops_r",)


def test_token_header_is_normalized():
    assert (
        EtsyTokenCredential(
            **{**CREDENTIAL, "access_token": " Bearer 123.token "}
        ).access_token
        == "123.token"
    )


@pytest.mark.parametrize(
    "operation,fields",
    [
        ("get_listing", {"listing_id": 0}),
        ("list_orders", {"shop_id": 12345678, "limit": 101}),
        (
            "update_listing",
            {"shop_id": 12345678, "listing_id": 192837465, "state": "draft"},
        ),
        (
            "update_listing_inventory",
            {
                "listing_id": 192837465,
                "products": [
                    {"offerings": [{"price": 8, "quantity": 3, "is_enabled": True}]}
                ],
            },
        ),
    ],
)
def test_invalid_config_is_rejected(operation, fields):
    with pytest.raises(ValidationError):
        node({"operation": operation, **fields})


@pytest.mark.asyncio
async def test_inventory_preserves_required_nullable_offering_field():
    config = {
        "operation": "update_listing_inventory",
        "listing_id": 192837465,
        "products": [
            {
                "offerings": [
                    {
                        "price": 8,
                        "quantity": 3,
                        "is_enabled": True,
                        "readiness_state_id": None,
                    }
                ]
            }
        ],
    }

    def respond(request):
        offering = json.loads(request.content)["products"][0]["offerings"][0]
        assert "readiness_state_id" in offering
        assert offering["readiness_state_id"] is None
        return httpx.Response(200, json=FIXTURES["update_listing_inventory"]["body"])

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch("nodes.etsy_node.httpx.AsyncClient", return_value=client):
        assert (await node(config).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_query_associations_use_declared_exploded_encoding():
    def respond(request):
        assert request.url.params.get_list("includes") == ["Images", "Shop"]
        assert "json" not in request.headers.get("Content-Type", "")
        return httpx.Response(200, json=FIXTURES["get_listing"]["body"])

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch("nodes.etsy_node.httpx.AsyncClient", return_value=client):
        result = await node(
            {
                "operation": "get_listing",
                "listing_id": 192837465,
                "includes": ["Images", "Shop"],
            }
        ).execute({})
    assert result["status"] == "success"
