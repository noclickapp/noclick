"""BILL webhook lifecycle and delivery, using BILL's published payloads."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest

from nodes.bill_node import BillNode, BillNodeConfig, BILL_TRIGGER_EVENTS
from nodes.tests.test_bill_node_mock import node

EVENTS = json.loads((Path(__file__).parent / 'fixtures/bill/events.json').read_text())
CREDENTIAL = {'credential_type': 'bill_session', 'dev_key': 'developer-secret',
              'session_id': 'session-secret', 'environment': 'sandbox'}


@pytest.mark.parametrize('fixture', EVENTS.values(), ids=EVENTS.keys())
def test_provider_documented_delivery(fixture):
    body = fixture['body']
    entity = body['metadata']['eventType'].split('.')[0]
    config = {'operation': f'on_{entity}_event', 'event_type': body['metadata']['eventType']}
    assert BillNode.filter_trigger_payload(body, config)
    assert not BillNode.filter_trigger_payload(body, {**config, 'event_type': 'other.event'})
    output = BillNode.resolve_trigger_payload(body, config)
    assert output['data'] is body
    event = BillNode.resolve_agent_event(output)
    if 'id' in body[entity]:
        assert body[entity]['id'] in event['text']
    assert body['metadata']['eventId'] in event['text']
    assert body['metadata']['organizationId'] in event['conversation_key']
    assert body['metadata']['eventType'] in event['title']
    if body['metadata']['eventType'] == 'payment.failed':
        assert 'Bank account is inactive.' in event['text']
        assert 'get_payment' not in event['text']
        assert 'get_bill' in event['text']
    else:
        assert f'get_{entity}' in event['text']


def test_signature_exact_request_bytes():
    body = json.dumps(EVENTS['bill.created']['body'], separators=(',', ':')).encode()
    signature = base64.b64encode(hmac.new(b'subscription-secret', body, hashlib.sha256).digest()).decode()
    config = {'signing_secret': 'subscription-secret'}
    assert BillNode.verify_webhook_signature(body, {'X-Bill-Sha-Signature': signature}, config)
    assert not BillNode.verify_webhook_signature(body + b' ', {'x-bill-sha-signature': signature}, config)
    assert not BillNode.verify_webhook_signature(body, {'x-bill-sha-signature': signature}, {'signing_secret': 'wrong'})
    assert not BillNode.verify_webhook_signature(body, {}, config)
    assert not BillNode.verify_webhook_signature(body, {'x-bill-sha-signature': signature}, {})


@pytest.mark.parametrize('operation', BILL_TRIGGER_EVENTS)
async def test_registration_cleanup_and_manual_run(operation):
    event_type = BILL_TRIGGER_EVENTS[operation][0]
    config = {'operation': operation, 'event_type': event_type}
    requests = []
    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={'id': 'subscription-1', 'securityKey': 'one-time-key'}) if request.method == 'POST' else httpx.Response(200)
    original = httpx.AsyncClient
    with patch('nodes.bill_node.httpx.AsyncClient', side_effect=lambda **kw: original(**kw, transport=httpx.MockTransport(transport))):
        extra = await BillNode._register_external_webhook(webhook_url='https://test.hooks.example.test/event', credential=CREDENTIAL, config=config, node_id='test')
        assert extra == {'external_webhook_id': 'subscription-1', 'signing_secret': 'one-time-key'}
        await BillNode._unregister_external_webhook(credential=CREDENTIAL, config={**config, **extra}, node_id='test')
        assert (await node(config).execute({}))['status'] == 'no_event'
    assert len(requests) == 2
    post, delete = requests
    assert str(post.url) == 'https://gateway.stage.bill.com/connect-events/v3/subscriptions'
    assert post.headers['devKey'] == CREDENTIAL['dev_key']
    assert post.headers['sessionId'] == CREDENTIAL['session_id']
    assert UUID(post.headers['X-Idempotent-Key']).version == 4
    assert json.loads(post.content) == {'name': 'NoClick test', 'status': {'enabled': True}, 'events': [{'type': event_type, 'version': '1'}], 'notificationUrl': 'https://test.hooks.example.test/event'}
    assert delete.method == 'DELETE'
    assert str(delete.url) == 'https://gateway.stage.bill.com/connect-events/v3/subscriptions/subscription-1'
    parsed = BillNodeConfig(config={**config, **extra}, credentials=CREDENTIAL)
    assert parsed.config.signing_secret == 'one-time-key'
    assert BillNode.registration_fingerprint_fields(config) == {'event_type': event_type}


async def test_refuses_unknown_event_before_registration():
    with pytest.raises(ValueError, match='supported BILL event'):
        await BillNode._register_external_webhook(webhook_url='https://test.hooks.example.test/event', credential=CREDENTIAL, config={'operation': 'on_bill_event', 'event_type': 'payment.failed'}, node_id='test')


async def test_registration_failure_does_not_expose_credentials():
    original = httpx.AsyncClient
    with patch('nodes.bill_node.httpx.AsyncClient', side_effect=lambda **kw: original(**kw, transport=httpx.MockTransport(lambda _: httpx.Response(401, text='session-secret developer-secret')))):
        with pytest.raises(ValueError) as error:
            await BillNode._register_external_webhook(webhook_url='https://test.hooks.example.test/event', credential=CREDENTIAL, config={'operation': 'on_bill_event', 'event_type': 'bill.created'}, node_id='test')
    assert 'session-secret' not in str(error.value)
    assert 'developer-secret' not in str(error.value)


def test_documented_bill_update_without_payment_term():
    # https://developer.bill.com/reference/updatebill (BillUpdateRequestDto.example)
    config = BillNodeConfig(config={
        'operation': 'update_bill', 'bill_id': '{{bill_id}}',
        'bill_line_items': json.dumps([{'id': '{{bill_line_item_id01}}', 'amount': 179,
                                     'description': 'USB audio interface (amount updated)'}]),
    }, credentials=CREDENTIAL)
    assert config.config.payment_term_id is None
