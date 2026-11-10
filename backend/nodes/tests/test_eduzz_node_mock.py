"""Exercise Eduzz's documented requests, responses, and signed event examples."""
import copy
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from nodes.eduzz_node import (
    BASE_URL, EduzzAccessTokenCredential, EduzzNode, EduzzNodeConfig,
    EduzzChangeSubscriptionBillingDayConfig, EduzzExtendEnrollmentAccessConfig,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'eduzz'
OPERATIONS = json.loads((FIXTURES / 'operations.json').read_text())
EVENTS = json.loads((FIXTURES / 'events.json').read_text())
LIFECYCLE = json.loads((FIXTURES / 'webhook_lifecycle.json').read_text())
CREDENTIAL = {'credential_type': 'eduzz_access_token', 'access_token': 'eduzz-test-access-token'}


def make_node(config):
    parsed = EduzzNodeConfig.model_validate({'config': config, 'credentials': CREDENTIAL})
    node = EduzzNode(node_id='test', node_type='automation-eduzz',
        node_data={'config': config}, config=parsed, sio=Mock())
    node.emit = AsyncMock()
    return node


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', OPERATIONS)
async def test_documented_operation_request_and_response(operation, monkeypatch):
    example = OPERATIONS[operation]
    calls = []

    async def request(client, method, url, **kwargs):
        calls.append((method, url, kwargs))
        response = example['response']
        return httpx.Response(response['status'], json=response['body'],
            request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    config = copy.deepcopy(example['config'])
    node = make_node(config)
    result = await node.execute({})
    assert result == {'status': 'success', 'operation': operation, 'data': example['response']['body']}
    assert len(calls) == 1
    method, url, kwargs = calls[0]
    expected_path = example['path']
    for field in ('id', 'email', 'teamId'):
        if ':' + field in expected_path:
            expected_path = expected_path.replace(':' + field, quote(str(config[field]), safe=''))
    assert (method, url) == (example['method'], BASE_URL + expected_path)
    assert kwargs['headers']['Authorization'] == 'Bearer ' + CREDENTIAL['access_token']
    if operation == 'list_sales':
        assert kwargs['params']['startDate'] == '2025-01-01T00:00:00Z'
        assert kwargs['params']['endDate'] == '2025-01-31T23:59:59Z'
    if operation == 'cancel_subscriptions':
        assert kwargs['json'] == {'subscriptions': ['123456789'], 'cancelReason': 'Problemas com o pagamento.'}
    if operation == 'change_subscription_billing_day':
        assert kwargs['json'] == {'dueDateDay': '1', 'motive': 'Solicitação do cliente'}
    if operation == 'create_school_student':
        assert kwargs['json'] == {k: config[k] for k in ('name', 'email', 'phone', 'document', 'tags')}


@pytest.mark.asyncio
async def test_provider_rejection_is_visible_and_never_success(monkeypatch):
    async def request(client, method, url, **kwargs):
        return httpx.Response(403, json={'message': 'Permission denied'}, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    with pytest.raises(ValueError, match='Eduzz API 403: Permission denied'):
        await make_node({'operation': 'get_account'}).execute({})


def test_manual_credential_default_and_no_oauth_side_effects():
    assert EduzzAccessTokenCredential(access_token='eduzz-valid-application-token').credential_type == 'eduzz_access_token'
    for token in ('https://console.eduzz.com', 'Bearer some-token', 'some\nheader'):
        with pytest.raises(ValidationError):
            EduzzAccessTokenCredential(access_token=token)
    with pytest.raises(ValidationError):
        EduzzAccessTokenCredential(credential_type='foreign_token', access_token='eduzz-valid-application-token')


def test_provider_constraints_are_validated_before_writes():
    with pytest.raises(ValidationError):
        EduzzChangeSubscriptionBillingDayConfig(id='12345', dueDateDay='31', motive='Solicitação do cliente')
    with pytest.raises(ValidationError):
        EduzzExtendEnrollmentAccessConfig(id='12345', expiredAt='2025-02-30T00:00:00Z')


@pytest.mark.asyncio
async def test_encoded_resource_id_cannot_replace_path(monkeypatch):
    request = AsyncMock(return_value={'id': 'value'})
    monkeypatch.setattr(EduzzNode, '_request', request)
    await make_node({'operation': 'get_customer', 'email': 'buyer+tag@example.com'}).execute({})
    assert request.call_args.args[2] == '/myeduzz/v1/customers/buyer%2Btag%40example.com'
    with pytest.raises(ValueError, match='resource ID'):
        await make_node({'operation': 'get_student', 'id': '..'}).execute({})


@pytest.mark.asyncio
async def test_webhook_creation_fetches_secret_activates_and_tears_down(monkeypatch):
    calls = []

    async def request(client, method, url, **kwargs):
        calls.append((method, url.removeprefix(BASE_URL), kwargs))
        path = url.removeprefix(BASE_URL)
        if path.endswith('/status'):
            key = 'POST /webhook/v1/subscription/:id/status'
        elif method == 'DELETE':
            key = 'DELETE /webhook/v1/subscription/:id'
        else:
            key = method + ' ' + path
        response = LIFECYCLE[key]
        return httpx.Response(response['status'],
            **({'json': response['body']} if response['body'] is not None else {}),
            request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    config = {'operation': 'on_event', 'event_type': 'myeduzz.invoice_paid'}
    registration = await EduzzNode._register_external_webhook(
        webhook_url='https://example.hooks.example.test', credential=CREDENTIAL, config=config, node_id='example')
    sid = LIFECYCLE['POST /webhook/v1/subscription']['body']['id']
    assert registration == {'external_webhook_id': sid,
        'signing_secret': LIFECYCLE['GET /webhook/v1/secret']['body']['secret']}
    assert calls[1][2]['json'] == {'name': 'NoClick example', 'url': 'https://example.hooks.example.test',
        'events': [{'name': 'myeduzz.invoice_paid'}], 'filters': []}
    assert calls[2][0:2] == ('POST', f'/webhook/v1/subscription/{sid}/status')
    assert calls[2][2]['json'] == {'status': 'active'}
    await EduzzNode._unregister_external_webhook(credential=CREDENTIAL,
        config={**config, **registration}, node_id='example')
    assert calls[3][0:2] == ('DELETE', f'/webhook/v1/subscription/{sid}')


@pytest.mark.asyncio
async def test_failed_activation_removes_disabled_subscription(monkeypatch):
    request = AsyncMock(side_effect=[LIFECYCLE['GET /webhook/v1/secret']['body'],
        LIFECYCLE['POST /webhook/v1/subscription']['body'], ValueError('Activation rejected'), None])
    monkeypatch.setattr(EduzzNode, '_request', request)
    with pytest.raises(ValueError, match='Activation rejected'):
        await EduzzNode._register_external_webhook(webhook_url='https://example.hooks.example.test',
            credential=CREDENTIAL, config={'event_type': 'myeduzz.invoice_paid'}, node_id='example')
    assert request.call_args.args[1] == 'DELETE'


@pytest.mark.parametrize('event', EVENTS)
def test_signed_documented_events_and_agent_turn(event):
    payload = EVENTS[event]
    body = json.dumps(payload).encode()
    secret = 'eduzz-documentation-test-secret'
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    config = {'event_type': event, 'signing_secret': secret}
    headers = {'X-Signature': signature}
    assert EduzzNode.verify_webhook_signature(body, headers, config)
    assert not EduzzNode.verify_webhook_signature(body + b' ', headers, config)
    assert not EduzzNode.verify_webhook_signature(body, {}, config)
    assert not EduzzNode.verify_webhook_signature(body, headers, {})
    assert EduzzNode.filter_trigger_payload(payload, config)
    assert not EduzzNode.filter_trigger_payload(payload, {'event_type': 'different.event'})
    output = EduzzNode.resolve_trigger_payload(payload, config)
    assert output == payload
    turn = EduzzNode.resolve_agent_event(output)
    data = payload['data']
    record = data['contract'] if event.startswith('myeduzz.contract_') else data
    customer = data['customer'] if event.startswith('myeduzz.contract_') else data['buyer']
    assert record['id'] == turn['conversation_key']
    assert customer['email'] in turn['text']
    assert event in turn['text']
    assert record['status'] in turn['text']


@pytest.mark.asyncio
async def test_ping_is_acknowledged_without_execution_and_manual_run_has_no_event():
    # https://developers.eduzz.com/docs/webhook/ping
    ping = {'id': 'l927c4root16a9zvq8v78lcr6', 'event': 'ping',
        'data': {'message': 'ping'}, 'sentDate': '2025-05-27T19:42:47.103Z'}
    assert EduzzNode.handle_webhook_handshake(json.dumps(ping).encode(), {}, {}) == {}
    assert EduzzNode.handle_webhook_handshake(b'invalid', {}, {}) is None
    assert EduzzNode.handle_webhook_handshake(json.dumps(EVENTS['myeduzz.invoice_paid']).encode(), {}, {}) is None
    result = await make_node({'operation': 'on_event'}).execute({})
    assert result['status'] == 'no_event'
