"""Exercise Katana writes and signed webhook lifecycle without a provider account.

Webhook fixtures retain the provider's published examples and their source URLs.
"""
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.katana_mrp_node import KatanaMRPAPIKeyCredential, KatanaMRPNode, KatanaMRPNodeConfig

FIXTURES = Path(__file__).parent / 'fixtures' / 'katana-mrp'
CREDENTIAL = {'credential_type': 'katana_mrp_api_key', 'api_key': 'test-api-key'}


def fixture(name):
    return json.loads((FIXTURES / f'{name}.json').read_text())['body']


def node(config):
    return KatanaMRPNode(node_id='test', node_type='automation-katana-mrp', node_data={'config': config},
        config=KatanaMRPNodeConfig.model_validate({'config': config, 'credentials': CREDENTIAL}), sio=Mock())


def transport(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr('nodes.katana_mrp_node.httpx.AsyncClient',
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_katana_mrp_sales_order_rows_and_authorization(monkeypatch):
    def handler(request):
        assert request.method == 'POST'
        assert str(request.url) == 'https://api.katanamrp.com/v1/sales_orders'
        assert request.headers['Authorization'] == 'Bearer test-api-key'
        assert json.loads(request.content) == {'customer_id': 1, 'sales_order_rows': [
            {'variant_id': 1, 'quantity': 2.0, 'price_per_unit': 150.0}]}
        return httpx.Response(200, json={'id': 8})
    transport(monkeypatch, handler)
    out = await node({'operation': 'create_sales_order', 'customer_id': 1,
        'sales_order_rows': '[{"variant_id":1,"quantity":2,"price_per_unit":150}]'}).execute({})
    assert out['data'] == {'id': 8}


@pytest.mark.asyncio
async def test_katana_mrp_purchase_order_rows(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == '/v1/purchase_orders'
        assert body['purchase_order_rows'] == [{'variant_id': 1, 'quantity': 2, 'price_per_unit': 10}]
        assert body['supplier_id'] == 1 and body['location_id'] == 1
        return httpx.Response(200, json={'id': 12})
    transport(monkeypatch, handler)
    await node({'operation': 'create_purchase_order', 'supplier_id': 1, 'location_id': 1,
        'purchase_order_rows': '[{"variant_id":1,"quantity":2,"price_per_unit":10}]'}).execute({})


@pytest.mark.asyncio
async def test_katana_mrp_update_does_not_send_absent_fields(monkeypatch):
    def handler(request):
        assert request.method == 'PATCH' and request.url.path == '/v1/manufacturing_orders/42'
        assert json.loads(request.content) == {'status': 'DONE', 'actual_quantity': 0}
        return httpx.Response(200, json={'id': 42, 'status': 'DONE'})
    transport(monkeypatch, handler)
    await node({'operation': 'update_manufacturing_order', 'id': 42, 'status': 'DONE', 'actual_quantity': 0}).execute({})
    with pytest.raises(ValueError, match='at least one'):
        await node({'operation': 'update_customer', 'id': 1}).execute({})


@pytest.mark.asyncio
async def test_katana_mrp_documented_pagination_and_false_filter(monkeypatch):
    def handler(request):
        assert dict(request.url.params) == {'page': '2', 'limit': '20', 'is_sellable': 'false'}
        return httpx.Response(200, json={'data': []})
    transport(monkeypatch, handler)
    assert (await node({'operation': 'list_products', 'page': 2, 'limit': 20, 'is_sellable': False}).execute({}))['data'] == {'data': []}


@pytest.mark.asyncio
async def test_katana_mrp_api_rejection_is_not_success(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(401, json={'message': 'Unauthorized'}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'list_customers'}).execute({})


def test_katana_mrp_manual_credential_default_and_invalid_rows():
    assert KatanaMRPAPIKeyCredential(api_key='issued-test-key').credential_type == 'katana_mrp_api_key'
    for rows in ('[]', 'not json', '[{"variant_id":1}]', '[{"variant_id":1,"quantity":-1}]'):
        with pytest.raises(ValidationError):
            node({'operation': 'create_sales_order', 'customer_id': 1, 'sales_order_rows': rows})
    with pytest.raises(ValidationError):
        node({'operation': 'get_sales_order', 'id': '../../customers'})


@pytest.mark.asyncio
async def test_katana_mrp_webhook_registration_and_cleanup(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == 'POST':
            assert json.loads(request.content) == {'url': 'https://example.hooks.example.test', 'subscribed_events': ['sales_order.delivered']}
            return httpx.Response(200, json=fixture('webhook_registration'))
        assert request.method == 'DELETE' and request.url.path == '/v1/webhooks/1'
        return httpx.Response(200, json={})
    transport(monkeypatch, handler)
    state = await KatanaMRPNode._register_external_webhook(webhook_url='https://example.hooks.example.test',
        credential=CREDENTIAL, config={}, node_id='test')
    assert state == {'external_webhook_id': '1', 'signing_secret': '73f82127d57a2cea'}
    await KatanaMRPNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id='test')
    assert len(requests) == 2
    with pytest.raises(ValueError, match='Invalid Katana'):
        await KatanaMRPNode._unregister_external_webhook(credential=CREDENTIAL,
            config={'external_webhook_id': '../../customers'}, node_id='test')


@pytest.mark.asyncio
async def test_katana_mrp_missing_webhook_secret_refuses_registration(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={'id': 1}))
    with pytest.raises(ValueError, match='secret token'):
        await KatanaMRPNode._register_external_webhook(webhook_url='https://example.hooks.example.test',
            credential=CREDENTIAL, config={}, node_id='test')


def test_katana_mrp_raw_body_signature_and_agent_event():
    payload = fixture('sales_order_delivered')
    raw = json.dumps(payload).encode()
    config = {'signing_secret': 'test-secret'}
    signature = hmac.new(b'test-secret', raw, hashlib.sha256).hexdigest()
    headers = {'X-Sha2-Signature': signature}
    assert KatanaMRPNode.verify_webhook_signature(raw, headers, config)
    assert not KatanaMRPNode.verify_webhook_signature(raw + b' ', headers, config)
    assert not KatanaMRPNode.verify_webhook_signature(raw, headers, {})
    assert not KatanaMRPNode.verify_webhook_signature(raw, {'x-sha2-signature': 'invalid'}, config)
    assert not KatanaMRPNode.verify_webhook_signature(raw, {}, config)
    assert KatanaMRPNode.filter_trigger_payload(payload, {})
    assert not KatanaMRPNode.filter_trigger_payload({'action': 'other'}, {})
    event = KatanaMRPNode.resolve_agent_event(KatanaMRPNode.resolve_trigger_payload(payload, {}))
    assert event['conversation_key'] == '<SALES_ORDER_ID>'
    assert 'DELIVERED' in event['text'] and 'get_sales_order' in event['text']
    assert 'https://api.katanamrp.com/v1/sales_orders/<SALES_ORDER_ID>' in event['text']


@pytest.mark.asyncio
async def test_katana_mrp_manual_trigger_has_no_event():
    assert (await node({'operation': 'on_sales_order_delivered'}).execute({}))['status'] == 'no_event'


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,selector', [
    ('list_products', {}, 'GET /products'),
    ('list_customers', {}, 'GET /customers'),
    ('get_sales_order', {'id': 1}, 'GET /sales_orders/{id}'),
    ('update_variant', {'id': 1, 'sales_price': 40}, 'PATCH /variants/{id}'),
])
async def test_katana_mrp_preserves_published_response_shapes(monkeypatch, operation, config, selector):
    examples = json.loads((FIXTURES / 'documented_responses.json').read_text())
    example = examples[selector]['body']
    transport(monkeypatch, lambda request: httpx.Response(200, json=example))
    result = await node({'operation': operation, **config}).execute({})
    assert result['data'] == example
    assert result['status'] == 'success'
