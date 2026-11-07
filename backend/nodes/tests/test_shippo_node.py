"""Shippo API-key schema and REST contracts without a live account."""

import json

import httpx
import pytest
from pydantic import ValidationError

from nodes.shippo_node import CONFIG_MODELS, OPERATIONS, ShippoNode, ShippoNodeConfig


def _config(operation: str, **fields):
    return ShippoNodeConfig.model_validate({
        "config": {"operation": operation, **fields},
        "credentials": {"credential_type": "shippo_api_key", "api_key": "shippo_test_example"},
    })


def _transport(monkeypatch, callback):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.shippo_node.httpx.AsyncClient",
        lambda *args, **kwargs: original(transport=httpx.MockTransport(callback)),
    )


def test_catalog_and_credential_schema_cover_shipping_workflows():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 71
    assert {"Addresses", "Shipments", "Transactions", "Tracking Status", "Refunds"} <= {
        op["category"] for op in OPERATIONS.values()
    }
    assert ShippoNode.connection_evidence.operation == "list_addresses"
    schema = ShippoNode.get_config_schema()
    assert '"ui:widget": "password"' in json.dumps(schema)
    with pytest.raises(ValidationError):
        _config("get_shipment")


@pytest.mark.asyncio
async def test_list_addresses_uses_shippo_token_version_and_page(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(200, json={
            "results": [{"object_id": "address-1", "name": "Acme"}],
            "next": "https://api.goshippo.com/addresses?page=2", "count": 12,
        })

    _transport(monkeypatch, callback)
    result = await ShippoNode._request("shippo_test_example", "list_addresses", {"query_json": '{"page":1}'})
    assert result["data"]["results"][0]["name"] == "Acme"
    assert result["next_page"].endswith("page=2")
    assert result["total_count"] == 12
    assert str(seen[0].url) == "https://api.goshippo.com/addresses?page=1"
    assert seen[0].headers["Authorization"] == "ShippoToken shippo_test_example"
    assert seen[0].headers["SHIPPO-API-VERSION"] == "2018-02-08"


@pytest.mark.asyncio
async def test_create_shipment_requires_address_and_parcels(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(201, json={"object_id": "shipment-1"})

    _transport(monkeypatch, callback)
    body = {"address_from": "sender", "address_to": "recipient", "parcels": ["parcel-1"]}
    result = await ShippoNode._request("shippo_test_example", "create_shipment", {"body_json": json.dumps(body)})
    assert result["data"]["object_id"] == "shipment-1"
    assert seen[0].url.path == "/shipments"
    assert json.loads(seen[0].content) == body
    with pytest.raises(ValueError, match="address_to, parcels"):
        await ShippoNode._request("shippo_test_example", "create_shipment", {"body_json": '{"address_from":"sender"}'})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_synchronous_label_requires_label_url_even_when_shippo_returns_success(monkeypatch):
    responses = [
        {
            "status": "SUCCESS", "label_url": None,
            "messages": [{"text": "Labels are not available while invoices are past due.",
                          "code": "usps_label_expired"}],
        },
        {"status": "SUCCESS", "label_url": "https://example.com/test-label.pdf"},
    ]

    _transport(monkeypatch, lambda request: httpx.Response(201, json=responses.pop(0)))
    with pytest.raises(ValueError, match="Shippo label was not created: Labels are not available"):
        await ShippoNode._request("shippo_test_example", "create_transaction", {
            "body_json": json.dumps({"rate": "rate-1", "async": False}),
        })

    result = await ShippoNode._request("shippo_test_example", "create_transaction", {
        "body_json": json.dumps({"rate": "rate-1", "async": False}),
    })
    assert result["status"] == "success"
    assert result["data"]["label_url"].endswith("test-label.pdf")


@pytest.mark.asyncio
async def test_tracking_path_is_encoded_and_api_error_is_reported(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(404, json={"detail": "Unknown tracking number"})

    _transport(monkeypatch, callback)
    with pytest.raises(ValueError, match="Shippo API error 404: Unknown tracking number"):
        await ShippoNode._request("shippo_test_example", "get_track", {
            "path_carrier": "usps", "path_trackingnumber": "a/b",
        })
    assert seen[0].url.raw_path.endswith(b"/tracks/usps/a%2Fb")
    with pytest.raises(ValueError, match="TrackingNumber is required"):
        await ShippoNode._request("shippo_test_example", "get_track", {
            "path_carrier": "usps", "path_trackingnumber": "..",
        })
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_carrier_oauth_returns_documented_redirect_without_following(monkeypatch):
    # Shippo's pinned public-api.yaml documents this 302 Location example.
    location = (
        "https://www.ups.com/lasso/signin?client_id=testClientID"
        "&redirect_uri=https://client.example.com/cb&response_type=code"
        "&scope=read&type=ups_com_api"
    )
    seen = []
    original = httpx.AsyncClient

    def callback(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": location})

    def client(*args, **kwargs):
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(callback), **kwargs)

    monkeypatch.setattr("nodes.shippo_node.httpx.AsyncClient", client)
    result = await ShippoNode._request("shippo_test_example", "initiate_oauth2_signin", {
        "path_carrieraccountobjectid": "2ccf5af209bb484cb20190d9cadbb61c",
        "query_redirect_uri": "https://client.example.com/cb",
    })
    assert result["status"] == "success"
    assert result["status_code"] == 302
    assert result["redirect_url"] == location
    assert len(seen) == 1
    assert seen[0].url.params["redirect_uri"] == "https://client.example.com/cb"
    assert seen[0].url.host == "api.goshippo.com"


@pytest.mark.asyncio
async def test_unexpected_redirect_still_reports_api_error(monkeypatch):
    _transport(monkeypatch, lambda request: httpx.Response(302))
    with pytest.raises(ValueError, match="Shippo API error 302"):
        await ShippoNode._request("shippo_test_example", "list_addresses", {})
