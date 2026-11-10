"""Shippo API-key schema and REST contracts without a live account."""

import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.binary_output import BinaryOutput
from nodes.shippo_node import CONFIG_MODELS, OPERATIONS, TRIGGER_EVENTS, TRIGGER_MODELS, ShippoNode, ShippoNodeConfig


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


@pytest.mark.asyncio
@pytest.mark.parametrize("headers, content_type, extension", [
    ({"Content-Type": "application/pdf"}, "application/pdf", ".pdf"),
    ({"Content-Type": "application/pdf; charset=binary"}, "application/pdf", ".pdf"),
    ({}, "application/octet-stream", ".bin"),
])
async def test_non_json_response_returns_binary_output(monkeypatch, headers, content_type, extension):
    payload = b"\x00\xffbinary download"
    _transport(monkeypatch, lambda request: httpx.Response(200, content=payload, headers=headers))

    result = await ShippoNode._request("shippo_test_example", "list_addresses", {})

    assert result["status"] == "success"
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == payload
    assert result["data"].content_type == content_type
    assert result["data"].filename == f"shippo-list_addresses{extension}"


@pytest.mark.asyncio
async def test_non_json_error_still_reports_api_error(monkeypatch):
    _transport(monkeypatch, lambda request: httpx.Response(502, text="Bad Gateway"))
    with pytest.raises(ValueError, match="Shippo API error 502: request failed"):
        await ShippoNode._request("shippo_test_example", "list_addresses", {})

# Exact payload examples from https://docs.goshippo.com/tracking/webhooks.


def _documented_event(event):
    return json.loads((Path(__file__).parent / 'fixtures' / 'shippo' / f'{event}.json').read_text())


@pytest.mark.parametrize('operation', TRIGGER_EVENTS)
@pytest.mark.asyncio
async def test_webhook_lifecycle_and_documented_delivery(monkeypatch, operation):
    event = TRIGGER_EVENTS[operation][0]
    payload = _documented_event(event)
    requests = []

    def callback(request):
        requests.append(request)
        if request.method == 'DELETE':
            return httpx.Response(204)
        body = json.loads(request.content)
        assert body == {'event': event, 'url': 'https://example.com/shippo-webhook', 'active': True, 'is_test': True}
        assert request.url.path == '/webhooks'
        return httpx.Response(201, json={**body, 'object_id': '9c9783fa0e1148c98eba040141801119'})

    _transport(monkeypatch, callback)
    config = _config(operation, is_test=True).config.model_dump()
    state = await ShippoNode._register_external_webhook(
        webhook_url='https://example.com/shippo-webhook', credential={'api_key': 'shippo_test_example'},
        config=config, node_id='test')
    assert state == {'external_webhook_id': '9c9783fa0e1148c98eba040141801119'}
    config.update(state)
    assert ShippoNode.filter_trigger_payload(payload, config)
    assert not ShippoNode.filter_trigger_payload({**payload, 'test': False}, config)
    assert not ShippoNode.filter_trigger_payload({**payload, 'event': 'unsupported'}, config)
    output = ShippoNode.resolve_trigger_payload(payload, config)
    assert output['data'] is payload
    agent_event = ShippoNode.resolve_agent_event(output)
    assert agent_event['conversation_key'] and agent_event['text']
    assert 'To act:' in agent_event['text']
    if event == 'track_updated':
        assert '9205590164917312751089' in agent_event['text']
        assert 'DELIVERED' in agent_event['text']
        assert 'Las Vegas' in agent_event['text']
    elif event.startswith('transaction_'):
        assert payload['data']['object_id'] in agent_event['text']
        assert payload['data']['created_by']['username'] in agent_event['text']
        assert payload['data']['label_url'] in agent_event['text']
    await ShippoNode._unregister_external_webhook(credential={'api_key': 'shippo_test_example'}, config=config, node_id='test')
    assert requests[-1].method == 'DELETE'
    assert requests[-1].url.path == '/webhooks/9c9783fa0e1148c98eba040141801119'
    assert all(r.headers['Authorization'] == 'ShippoToken shippo_test_example' for r in requests)


def test_hmac_signature_follows_shippo_documented_algorithm():
    body = json.dumps(_documented_event('track_updated')).encode()
    timestamp = '1688493073'
    secret = 'test-hmac-secret'
    signature = hmac.new(secret.encode(), timestamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    headers = {'Shippo-Auth-Signature': f't={timestamp},v1={signature}'}
    config = {'hmac_secret': secret}
    assert ShippoNode.verify_webhook_signature(body, headers, config)
    assert ShippoNode.verify_webhook_signature(body, {k.lower():v for k,v in headers.items()}, config)
    assert not ShippoNode.verify_webhook_signature(body + b' ', headers, config)
    assert not ShippoNode.verify_webhook_signature(body, headers, {'hmac_secret': 'wrong'})
    assert not ShippoNode.verify_webhook_signature(body, {}, config)
    assert not ShippoNode.verify_webhook_signature(body, {'Shippo-Auth-Signature': 't=no,v1=bad'}, config)
    assert ShippoNode.verify_webhook_signature(body, {}, {})


@pytest.mark.parametrize('operation', TRIGGER_EVENTS)
@pytest.mark.asyncio
async def test_trigger_manual_run_has_no_event_and_schema_declares_trigger(operation):
    node = ShippoNode(node_id='test', node_type='automation-shippo', node_data={}, config=_config(operation))
    result = await node.execute({'event': 'invented'})
    assert result['status'] == 'no_event'
    assert result['data'] == {}
    assert TRIGGER_MODELS[operation].model_json_schema()['properties']['operation']['x-is-trigger'] is True
    assert ShippoNode.registration_fingerprint_fields({'is_test': True}) != ShippoNode.registration_fingerprint_fields({})


@pytest.mark.asyncio
async def test_registration_requires_webhook_id_and_cleanup_handles_missing_registration(monkeypatch):
    _transport(monkeypatch, lambda request: httpx.Response(201, json={}))
    with pytest.raises(ValueError, match='webhook ID'):
        await ShippoNode._register_external_webhook(webhook_url='https://example.com', credential={'api_key':'token'},
                                                  config={'operation':'on_tracking_updated'}, node_id='test')
    await ShippoNode._unregister_external_webhook(credential=None, config={}, node_id='test')
