"""Increase's published examples through real HTTP serialization, plus signed events."""
import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.increase_node import IncreaseAPIKeyCredential, IncreaseNode, IncreaseNodeConfig, OPERATIONS

FIXTURES = Path(__file__).parent / 'fixtures/increase'
REQUESTS = json.loads((FIXTURES / 'requests.json').read_text())
RESPONSES = json.loads((FIXTURES / 'responses.json').read_text())
EVENT = json.loads((FIXTURES / 'event.json').read_text())['body']
TOKEN = 'increase-offline-test-key'


def node(config, environment='production'):
    parsed = IncreaseNodeConfig.model_validate({'config': config, 'credentials': {'api_key': TOKEN, 'environment': environment}})
    return IncreaseNode(node_id='increase-test', node_type='automation-increase', node_data={}, config=parsed)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(REQUESTS))
async def test_increase_provider_examples(operation):
    case = REQUESTS[operation]
    with respx.mock(assert_all_called=True) as router:
        route = router.request(case['method'], 'https://api.increase.com' + case['path']).mock(
            return_value=httpx.Response(200, json=RESPONSES[operation]['body']))
        result = await node(case['config']).execute({})
    assert route.call_count == 1
    request = route.calls[0].request
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert dict(request.url.params) == case['query']
    assert (json.loads(request.content) if request.content else None) == case['body']
    assert result['data'] == RESPONSES[operation]['body']
    assert set(REQUESTS) == set(OPERATIONS)


@pytest.mark.asyncio
async def test_increase_pagination_filters_and_sandbox():
    with respx.mock as router:
        route = router.get('https://sandbox.increase.com/transactions').mock(return_value=httpx.Response(200, json={'data': [], 'next_cursor': 'next'}))
        result = await node({'operation': 'list_transactions', 'account_id': 'account_123', 'cursor': 'opaque==',
                             'limit': 25, 'created_after': '2026-01-01T00:00:00Z'}, 'sandbox').execute({})
    assert dict(route.calls[0].request.url.params) == {'account_id': 'account_123', 'cursor': 'opaque==', 'limit': '25', 'created_at.after': '2026-01-01T00:00:00Z'}
    assert result['data']['next_cursor'] == 'next'


@pytest.mark.asyncio
async def test_increase_idempotency_header():
    config = {**REQUESTS['create_account_transfer']['config'], 'idempotency_key': 'liquidity-job-123'}
    with respx.mock as router:
        route = router.post('https://api.increase.com/account_transfers').mock(return_value=httpx.Response(200, json=RESPONSES['create_account_transfer']['body']))
        await node(config).execute({})
    request = route.calls[0].request
    assert request.headers['Idempotency-Key'] == config['idempotency_key']
    assert 'idempotency_key' not in json.loads(request.content)


@pytest.mark.asyncio
async def test_increase_webhook_registration_and_deletion():
    credential = {'api_key': TOKEN, 'environment': 'sandbox'}
    subscription = 'event_subscription_001dzz0r20rcdxgb013zqb8m04g'
    with respx.mock as router:
        create = router.post('https://sandbox.increase.com/event_subscriptions').mock(return_value=httpx.Response(200, json={'id': subscription}))
        delete = router.patch('https://sandbox.increase.com/event_subscriptions/' + subscription).mock(return_value=httpx.Response(200, json={'id': subscription, 'status': 'deleted'}))
        registered = await IncreaseNode._register_external_webhook(webhook_url='https://example.hooks.example.test', credential=credential, config={'event_category': 'transaction.created'}, node_id='test')
        await IncreaseNode._unregister_external_webhook(credential=credential, config=registered, node_id='test')
    body = json.loads(create.calls[0].request.content)
    assert body == {'url': 'https://example.hooks.example.test', 'shared_secret': registered['signing_secret'], 'status': 'active', 'selected_event_categories': ['transaction.created']}
    assert len(registered['signing_secret']) == 64
    assert json.loads(delete.calls[0].request.content) == {'status': 'deleted'}


def sign(body, secret, timestamp=None):
    timestamp = str(timestamp or int(time.time()))
    message = EVENT['id'] + '.' + timestamp + '.'
    digest = base64.b64encode(hmac.new(secret.encode(), message.encode() + body, hashlib.sha256).digest()).decode()
    return {'Webhook-Id': EVENT['id'], 'Webhook-Timestamp': timestamp, 'Webhook-Signature': 'v1,' + digest}


def test_increase_signature_integrity_rotation_and_replay():
    body = json.dumps(EVENT).encode()
    config = {'signing_secret': 'test-raw-secret'}
    headers = sign(body, config['signing_secret'])
    assert IncreaseNode.verify_webhook_signature(body, headers, config)
    headers['Webhook-Signature'] = 'v1,old ' + headers['Webhook-Signature']
    assert IncreaseNode.verify_webhook_signature(body, headers, config)
    assert not IncreaseNode.verify_webhook_signature(body + b' ', headers, config)
    assert not IncreaseNode.verify_webhook_signature(body, headers, {'signing_secret': 'wrong'})
    assert not IncreaseNode.verify_webhook_signature(body, sign(body, config['signing_secret'], int(time.time()) - 301), config)
    assert not IncreaseNode.verify_webhook_signature(body, {}, config)
    headers['Webhook-Id'] = 'altered'
    assert not IncreaseNode.verify_webhook_signature(body, headers, config)


@pytest.mark.asyncio
async def test_increase_documented_event_and_agent_turn():
    result = await node({'operation': 'on_event'}).execute(EVENT)
    turn = IncreaseNode.resolve_agent_event(result)
    assert IncreaseNode.resolve_agent_event(EVENT) == turn
    assert turn['conversation_key'] == EVENT['associated_object_id']
    assert EVENT['associated_object_id'] in turn['text'] and EVENT['id'] in turn['text']
    assert EVENT['created_at'] in turn['text']
    assert IncreaseNode.filter_trigger_payload(EVENT, {'event_category': 'account.created'})
    assert not IncreaseNode.filter_trigger_payload(EVENT, {'event_category': 'transaction.created'})
    assert not IncreaseNode.filter_trigger_payload({}, {})
    assert (await node({'operation': 'on_event'}).execute({}))['status'] == 'no_event'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'status': 401, 'title': 'Unauthorized', 'detail': 'API key is invalid'}), (429, {'detail': 'Rate limit exceeded'}), (302, {})])
async def test_increase_api_errors(status, body):
    with respx.mock as router:
        router.get('https://api.increase.com/accounts').mock(return_value=httpx.Response(status, json=body))
        with pytest.raises(ValueError, match=f'Increase API error {status}'):
            await node({'operation': 'list_accounts'}).execute({})


@pytest.mark.parametrize('patch', [{'account_number': None, 'routing_number': None}, {'external_account_id': 'external_account_123'}, {'amount': 0}])
def test_increase_invalid_ach_destination(patch):
    with pytest.raises(ValidationError):
        node({**REQUESTS['create_ach_transfer']['config'], **patch})


def test_increase_manual_credential_and_input_validation():
    assert IncreaseAPIKeyCredential(api_key=TOKEN).credential_type == 'increase_api_key'
    for config in [{'operation': 'get_account', 'account_id': '../secrets'}, {'operation': 'list_accounts', 'limit': 101}, {'operation': 'list_accounts', 'created_after': '1'}, {'operation': 'update_card', 'card_id': 'card_123'}]:
        with pytest.raises(ValidationError):
            node(config)
