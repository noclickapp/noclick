"""Execute every Mollie operation against provider-published response examples."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from nodes import mollie_1_node as native
from nodes.core.registry import NodeFactory, NODE_REGISTRY

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/mollie-1/published.json').read_text())
PAYMENT = 'tr_5B8cwPMGnU6qLbRvo7qEZo'
CUSTOMER = 'cst_5B8cwPMGnU'
SUBSCRIPTION = 'sub_rVKGtNd6s3'
REFUND = 're_4qqhO89gsT'
LINK = 'pl_4Y0eZitmBnQ6IDoMqZQKh'
AMOUNT = {'currency': 'EUR', 'value': '10.00'}
TOKEN = 'synthetic-mollie-test-key'
CASES = {
    'list_payments': {'limit': 5, 'from_id': PAYMENT, 'sort': 'desc'},
    'get_payment': {'payment_id': PAYMENT},
    'create_payment': {'amount': AMOUNT, 'description': 'Chess Board', 'redirect_url': 'https://example.org/redirect', 'webhook_url': 'https://example.org/webhooks', 'customer_id': CUSTOMER, 'sequence_type': 'first', 'metadata': {'order_id': '12345'}, 'idempotency_key': 'order-12345'},
    'update_payment': {'payment_id': PAYMENT, 'description': 'Chess Board', 'cancel_url': 'https://example.org/cancel'},
    'cancel_payment': {'payment_id': PAYMENT},
    'create_refund': {'payment_id': PAYMENT, 'amount': AMOUNT, 'description': 'Order', 'idempotency_key': 'refund-12345'},
    'list_refunds': {'payment_id': PAYMENT, 'from_id': REFUND},
    'get_refund': {'payment_id': PAYMENT, 'refund_id': REFUND},
    'cancel_refund': {'payment_id': PAYMENT, 'refund_id': REFUND},
    'list_customers': {'from_id': CUSTOMER, 'sort': 'asc'},
    'get_customer': {'customer_id': CUSTOMER},
    'create_customer': {'name': 'Jane Doe', 'email': 'test@example.org', 'metadata': {'order_id': '12345'}},
    'update_customer': {'customer_id': CUSTOMER, 'email': 'jane@example.org'},
    'delete_customer': {'customer_id': CUSTOMER},
    'list_customer_payments': {'customer_id': CUSTOMER, 'from_id': PAYMENT},
    'create_subscription': {'customer_id': CUSTOMER, 'amount': AMOUNT, 'interval': '1 month', 'description': 'Subscription of streaming channel', 'times': 6, 'start_date': '2025-01-01', 'webhook_url': 'https://example.com/webhook'},
    'list_subscriptions': {'customer_id': CUSTOMER, 'from_id': SUBSCRIPTION},
    'get_subscription': {'customer_id': CUSTOMER, 'subscription_id': SUBSCRIPTION},
    'update_subscription': {'customer_id': CUSTOMER, 'subscription_id': SUBSCRIPTION, 'interval': '2 weeks', 'amount': AMOUNT, 'start_date': '2025-01-01'},
    'cancel_subscription': {'customer_id': CUSTOMER, 'subscription_id': SUBSCRIPTION},
    'create_payment_link': {'description': 'Bicycle tires', 'amount': AMOUNT, 'redirect_url': 'https://webshop.example.org/thanks', 'reusable': True, 'expires_at': '2029-12-24T11:00:16Z'},
    'list_payment_links': {'from_id': LINK},
    'get_payment_link': {'payment_link_id': LINK},
    'update_payment_link': {'payment_link_id': LINK, 'description': 'Bicycle tires', 'archived': True},
    'delete_payment_link': {'payment_link_id': LINK},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=True):
    data = {'config': config}
    if credential:
        data['credentials'] = {'credential_type': 'mollie_1_api_key', 'api_key': TOKEN}
    return NodeFactory.create_node(node_id='mollie-test', node_type='automation-mollie-1', node_data=data)


def intercept(monkeypatch, body, status=200, content_type='application/hal+json'):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={'Content-Type': content_type}) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs == {'timeout': 30, 'follow_redirects': False, 'trust_env': False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.parametrize('operation', CASES)
@pytest.mark.asyncio
async def test_mollie_1_published_contract(monkeypatch, operation):
    fixture = EXAMPLES[operation.replace('_', '-')]
    config = copy.deepcopy(CASES[operation])
    requests = intercept(monkeypatch, fixture['response'], fixture['status'])
    result = await node({'operation': operation, **config}).execute({})
    assert result['status'] == 'success' and len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method']
    path = fixture['path']
    for placeholder, value in {'paymentId': PAYMENT, 'customerId': CUSTOMER, 'subscriptionId': SUBSCRIPTION, 'refundId': REFUND, 'paymentLinkId': LINK}.items():
        path = path.replace('{' + placeholder + '}', value)
    assert request.url.path == path and request.url.host == 'api.mollie.com'
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.headers['Accept'] == 'application/hal+json'
    if operation.startswith('list_'):
        assert result['page_only'] is True and len(result['items']) == 1
        assert result['next_from'] is not None
        assert request.url.params['from'] == config['from_id']
        assert request.url.params['limit'] == str(config.get('limit', 50))
        assert request.content == b''
    elif fixture['status'] == 204:
        assert result == {'status': 'success', 'deleted': True}
    else:
        assert result['data'] == fixture['response']
    if request.method in {'POST', 'PATCH'}:
        body = json.loads(request.content)
        assert 'idempotency_key' not in body and 'profileId' not in body and 'testmode' not in body
        assert not any('_' in key for key in body)
        if 'amount' in config:
            assert body['amount'] == AMOUNT
        if 'idempotency_key' in config:
            assert request.headers['Idempotency-Key'] == config['idempotency_key']
    else:
        assert request.content == b''
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_mollie_1_exact_wire_field_names(monkeypatch):
    requests = intercept(monkeypatch, EXAMPLES['create-payment']['response'], 201)
    await node({'operation': 'create_payment', **CASES['create_payment']}).execute({})
    assert json.loads(requests[0].content) == {'amount': AMOUNT, 'description': 'Chess Board', 'redirectUrl': 'https://example.org/redirect', 'webhookUrl': 'https://example.org/webhooks', 'customerId': CUSTOMER, 'sequenceType': 'first', 'metadata': {'order_id': '12345'}}
    requests = intercept(monkeypatch, EXAMPLES['create-subscription']['response'], 201)
    await node({'operation': 'create_subscription', **CASES['create_subscription']}).execute({})
    assert json.loads(requests[0].content) == {'amount': AMOUNT, 'interval': '1 month', 'description': 'Subscription of streaming channel', 'times': 6, 'startDate': '2025-01-01', 'webhookUrl': 'https://example.com/webhook'}


@pytest.mark.asyncio
async def test_mollie_1_empty_customers_are_valid_evidence(monkeypatch):
    requests = intercept(monkeypatch, {'count': 0, '_embedded': {'customers': []}, '_links': {'next': None}})
    assert (await node({'operation': 'list_customers'}).execute({}))['items'] == []
    assert native.MollieNode.connection_evidence.operation == 'list_customers'
    assert native.MollieAPIKeyCredential(api_key=TOKEN).credential_type == 'mollie_1_api_key'
    assert 'automation-mollie-1' in NODE_REGISTRY and len(requests) == 1


@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
@pytest.mark.asyncio
async def test_mollie_1_rejection_does_not_retry_write(monkeypatch, status):
    requests = intercept(monkeypatch, {'status': status, 'title': 'Rejected', 'detail': 'Provider refusal'}, status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'create_refund', **CASES['create_refund']}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize('config', [
    {'operation': 'get_payment', 'payment_id': 'tr_../bad'},
    {'operation': 'create_payment', **CASES['create_payment'], 'customer_id': None},
    {'operation': 'get_customer', 'customer_id': 'https://foreign.test'},
    {'operation': 'create_subscription', **CASES['create_subscription'], 'interval': '13 months'},
    {'operation': 'create_subscription', **CASES['create_subscription'], 'interval': '0 days'},
    {'operation': 'create_payment', **CASES['create_payment'], 'profileId': 'pfl_foreign'},
    {'operation': 'create_payment', **CASES['create_payment'], 'idempotency_key': 'bad\r\nheader'},
    {'operation': 'create_payment', **CASES['create_payment'], 'amount': {'currency': 'EUR', 'value': 10.0}},
])
def test_mollie_1_invalid_config_refused(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize('body,content_type', [({}, 'application/hal+json'), ({'detail': 'Rejected'}, 'application/hal+json'), ({'count': 1, '_embedded': {'customers': 'bad'}}, 'application/hal+json'), ({'count': 0, '_embedded': {'customers': []}}, 'text/html')])
@pytest.mark.asyncio
async def test_mollie_1_bad_response_refused(monkeypatch, body, content_type):
    intercept(monkeypatch, body, content_type=content_type)
    with pytest.raises(ValueError):
        await node({'operation': 'list_customers'}).execute({})


@pytest.mark.asyncio
async def test_mollie_1_pagination_never_follows_provider_url(monkeypatch):
    body = copy.deepcopy(EXAMPLES['list-customers']['response'])
    body['_links']['next']['href'] = 'https://foreign.test/v2/customers?from=cst_next'
    requests = intercept(monkeypatch, body)
    with pytest.raises(ValueError, match='pagination link'):
        await node({'operation': 'list_customers'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_mollie_1_empty_update_and_missing_key_make_no_request(monkeypatch):
    requests = intercept(monkeypatch, {})
    for config, credential in [({'operation': 'update_payment', 'payment_id': PAYMENT}, True), ({'operation': 'list_payments'}, False)]:
        with pytest.raises(ValueError):
            await node(config, credential).execute({})
    assert requests == []


EVENTS = json.loads((Path(__file__).parent / 'fixtures/mollie-1/events.json').read_text())
REGISTRATION = json.loads((Path(__file__).parent / 'fixtures/mollie-1/webhook-registration.json').read_text())['body']
ADVANCED = {'credential_type': 'mollie_1_advanced_access_token', 'access_token': 'synthetic-advanced-token'}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,event', native.TRIGGER_EVENTS.items())
async def test_mollie_1_webhook_lifecycle(monkeypatch, operation, event):
    requests = intercept(monkeypatch, REGISTRATION, 201)
    config = {'operation': operation, 'testmode': True}
    registered = await native.MollieNode._register_external_webhook(
        webhook_url='https://example.org/webhooks', credential=ADVANCED, config=config, node_id='mollie-test')
    assert registered == {'external_webhook_id': REGISTRATION['id'], 'signing_secret': REGISTRATION['webhookSecret']}
    assert requests[0].url.path == '/v2/webhooks'
    assert requests[0].headers['Authorization'] == 'Bearer ' + ADVANCED['access_token']
    assert json.loads(requests[0].content) == {'name': 'NoClick mollie-test', 'url': 'https://example.org/webhooks', 'eventTypes': [event], 'testmode': True}
    requests = intercept(monkeypatch, None, 204)
    await native.MollieNode._unregister_external_webhook(
        credential=ADVANCED, config={**config, **registered}, node_id='mollie-test')
    assert requests[0].method == 'DELETE'
    assert requests[0].url.path == '/v2/webhooks/' + REGISTRATION['id']
    assert json.loads(requests[0].content) == {'testmode': True}


@pytest.mark.parametrize('operation,event', native.TRIGGER_EVENTS.items())
def test_mollie_1_published_event_routing_and_agent_context(operation, event):
    for name, fixture in EVENTS.items():
        body = copy.deepcopy(fixture['body'])
        body['_webhook'] = {'headers': {'X-Mollie-Signature': 'redacted'}}
        config = {'operation': operation}
        expected = name == event or (event == 'payment-link.paid' and name.startswith('payment-link.paid.'))
        assert native.MollieNode.filter_trigger_payload(body, config) is expected
        if not expected:
            continue
        output = native.MollieNode.resolve_trigger_payload(body, config)
        assert output['event_type'] == event
        assert '_webhook' not in output['data']
        agent = native.MollieNode.resolve_agent_event(output)
        entity_id = body['entityId'] if body['resource'] == 'event' else body['id']
        assert entity_id in agent['text']
        assert agent['conversation_key'] == 'mollie:' + entity_id
        assert 'Mollie:' in agent['text']
        if 'amount' in output['data']:
            assert output['data']['amount']['value'] in agent['text']
        if 'paymentId' in output['data']:
            assert output['data']['paymentId'] in agent['text']


def test_mollie_1_signature_rejects_forgery_and_missing_secrets():
    import hashlib
    import hmac
    body = json.dumps(EVENTS['payment.paid']['body']).encode()
    secret = REGISTRATION['webhookSecret']
    signature = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {'X-Mollie-Signature': signature}
    config = {'signing_secret': secret}
    assert native.MollieNode.verify_webhook_signature(body, headers, config)
    assert native.MollieNode.verify_webhook_signature(body, {'x-mollie-signature': signature}, config)
    assert not native.MollieNode.verify_webhook_signature(body + b' ', headers, config)
    assert not native.MollieNode.verify_webhook_signature(body, {}, config)
    assert not native.MollieNode.verify_webhook_signature(body, headers, {})
    assert not native.MollieNode.verify_webhook_signature(body, headers, {'signing_secret': 'wrong'})


@pytest.mark.asyncio
async def test_mollie_1_trigger_credential_boundary_and_manual_run(monkeypatch):
    requests = intercept(monkeypatch, REGISTRATION, 201)
    with pytest.raises(ValueError, match='advanced access token'):
        await native.MollieNode._register_external_webhook(webhook_url='https://example.org/webhooks',
            credential={'api_key': TOKEN}, config={'operation': 'on_payment_paid'}, node_id='test')
    assert requests == []
    trigger = NodeFactory.create_node(node_id='test', node_type='automation-mollie-1',
        node_data={'config': {'operation': 'on_payment_paid'}, 'credentials': ADVANCED})
    result = await trigger.execute({})
    assert result['status'] == 'no_event'
    assert native.MollieNode.resolve_agent_event(result) is None
    assert native.MollieNode.operation_credential_types('on_payment_paid') == {'mollie_1_advanced_access_token'}
    assert native.MollieNode.operation_credential_types('create_payment') == {'mollie_1_api_key'}
    assert native.MollieAdvancedAccessTokenCredential(access_token='access_example').credential_type == 'mollie_1_advanced_access_token'
    # The advanced-token connect probe uses the integration's documented customer list endpoint.
    intercept(monkeypatch, EXAMPLES['list-customers']['response'])
    probe = NodeFactory.create_node(node_id='test', node_type='automation-mollie-1',
        node_data={'config': {'operation': 'list_customers'}, 'credentials': ADVANCED})
    assert (await probe.execute({}))['status'] == 'success'
