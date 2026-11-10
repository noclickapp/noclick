"""Webhook lifecycle and deliveries use Fatture in Cloud's published examples.

The JWT tests use an ephemeral EC key to exercise the documented ES256 scheme,
with the production verifier pinned to the public key from the provider docs.
"""
import copy
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from nodes import fatture_in_cloud_node as native
from nodes.tests.test_fatture_in_cloud_node_mock import credential, node, transport

FIXTURES = Path(__file__).parent / 'fixtures' / 'fatture-in-cloud'
EXAMPLE = json.loads((FIXTURES / 'ClientCreatedEvent.json').read_text())
CONFIG = {'operation': 'on_event', 'company_id': 108061,
          'event_type': 'it.fattureincloud.webhooks.entities.clients.create',
          'webhook_url': 'https://example.com/notifications'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def signing(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(native, 'WEBHOOK_PUBLIC_KEY', public)
    claims = {'jti': EXAMPLE['headers']['ce-id'], 'iss': native.BASE,
              'sub': 'company:108061', 'aud': [CONFIG['webhook_url']],
              'iat': int(time.time()), 'exp': int(time.time()) + 10800, 'aid': 198}
    def sign(**changes):
        return {**EXAMPLE['headers'], 'Authorization': 'Bearer ' + jwt.encode(
            {**claims, **changes}, key, algorithm='ES256')}
    return sign


@pytest.mark.asyncio
async def test_fatture_in_cloud_registration_and_cleanup(monkeypatch):
    # Exact provider subscription response example, copied from the pinned contract.
    response = json.loads((FIXTURES / 'CreateWebhooksSubscriptionResponse.json').read_text())
    response.pop("warnings")  # Exercise successful registration separately from documented warnings.
    requests = transport(monkeypatch, response)
    result = await native.FattureInCloudNode._register_external_webhook(
        webhook_url=CONFIG['webhook_url'], credential=credential(), config=CONFIG, node_id='trigger')
    assert result == {'external_webhook_id': response['data']['id']}
    assert requests[0].url.path == '/c/108061/subscriptions'
    assert requests[0].method == 'POST'
    assert json.loads(requests[0].content) == {'data': {'sink': CONFIG['webhook_url'],
        'types': [CONFIG['event_type']], 'verification_method': 'header', 'config': {'mapping': 'binary'}}}
    requests = transport(monkeypatch, empty=True)
    await native.FattureInCloudNode._unregister_external_webhook(
        credential=credential(), config={**CONFIG, **result}, node_id='trigger')
    assert requests[0].method == 'DELETE'
    assert requests[0].url.path == '/c/108061/subscriptions/' + result['external_webhook_id']


@pytest.mark.asyncio
async def test_fatture_in_cloud_registration_warning_and_missing_id(monkeypatch):
    request = AsyncMock(side_effect=[{'data': {'id': 'SUB230'}, 'warnings': ['Already registered']}, {}])
    monkeypatch.setattr(native.FattureInCloudNode, '_request', request)
    with pytest.raises(ValueError, match='could not subscribe'):
        await native.FattureInCloudNode._register_external_webhook(
            webhook_url=CONFIG['webhook_url'], credential=credential(), config=CONFIG, node_id='trigger')
    assert request.call_args.args[1:] == ('DELETE', '/c/108061/subscriptions/SUB230')
    request.side_effect = None
    request.return_value = {'data': {}}
    with pytest.raises(ValueError, match='subscription ID'):
        await native.FattureInCloudNode._register_external_webhook(
            webhook_url=CONFIG['webhook_url'], credential=credential(), config=CONFIG, node_id='trigger')


def test_fatture_in_cloud_jwt_and_verification_handshake(signing):
    cls = native.FattureInCloudNode
    headers = signing()
    assert cls.verify_webhook_signature(json.dumps(EXAMPLE['body']).encode(), headers, CONFIG)
    challenge = '292ff90a85ae68be5be1b2808a56cd183c3e8f72373b6cdda8e9dfd8e08f0f05'
    headers.update({'x-fic-verification-challenge': challenge, '__method__': 'GET'})
    # Registration can challenge before the webhook URL mirror is saved.
    assert cls.handle_webhook_handshake(b'', headers, {'company_id': 108061}) == {'verification': challenge}
    assert cls.handle_webhook_handshake(b'', {**headers, '__method__': 'POST'}, CONFIG) is None
    assert cls.handle_webhook_handshake(b'', {'x-fic-verification-challenge': challenge}, CONFIG) is None
    assert not cls.verify_webhook_signature(b'{}', {}, CONFIG)
    assert not cls.verify_webhook_signature(b'{}', {**signing(), 'ce-id': 'wrong'}, CONFIG)
    assert not cls.verify_webhook_signature(b'{}', {**signing(), 'ce-subject': 'company:5'}, CONFIG)
    assert not cls.verify_webhook_signature(b'{}', signing(), {**CONFIG, 'company_id': 5})
    assert not cls.verify_webhook_signature(b'{}', signing(), {**CONFIG, 'webhook_url': None})


@pytest.mark.parametrize('changes', [{'aud': ['https://other.example']}, {'iss': 'https://evil.example'},
    {'sub': 'company:5'}, {'exp': 1}, {'iat': int(time.time()) + 9999}])
def test_fatture_in_cloud_rejects_invalid_jwt_claims(signing, changes):
    assert not native.FattureInCloudNode.verify_webhook_signature(b'{}', signing(**changes), CONFIG)


def test_fatture_in_cloud_rejects_forged_signature(signing):
    headers = signing()
    headers['Authorization'] += 'x'
    assert not native.FattureInCloudNode.verify_webhook_signature(b'{}', headers, CONFIG)


@pytest.mark.parametrize('event_type', native.WEBHOOK_EVENTS)
def test_fatture_in_cloud_documented_ids_only_events(event_type):
    # Notifications docs apply the same Binary data.ids body to all listed event types.
    config = {**CONFIG, 'event_type': event_type}
    payload = {**copy.deepcopy(EXAMPLE['body']), '_webhook': {
        'headers': {**EXAMPLE['headers'], 'ce-type': event_type}}}
    cls = native.FattureInCloudNode
    assert cls.filter_trigger_payload(payload, config)
    output = cls.resolve_trigger_payload(payload, config)
    assert output['ids'] == [3062300] and output['company_id'] == 108061
    message = cls.resolve_agent_event(output)
    assert '3062300' in message['text'] and '108061' in message['text']
    assert native.WEBHOOK_EVENTS[event_type][1] in message['text']
    if not event_type.endswith('.delete'):
        assert native.WEBHOOK_EVENTS[event_type][2] in message['text']
    assert 'Authorization' not in str(output)
    assert not cls.filter_trigger_payload(payload, {**config, 'company_id': 2})
    assert not cls.filter_trigger_payload(payload, {**config, 'event_type': 'welcome'})
    payload['data']['ids'] = []
    assert not cls.filter_trigger_payload(payload, config)


@pytest.mark.asyncio
async def test_fatture_in_cloud_manual_trigger_run_waits():
    result = await node(CONFIG).execute({})
    assert result['status'] == 'no_event'


def test_fatture_in_cloud_fingerprint_and_schema():
    cls = native.FattureInCloudNode
    assert cls.registration_fingerprint_fields(CONFIG) == {
        'company_id': 108061, 'event_type': CONFIG['event_type']}
    schema = native.OnEvent.model_json_schema()
    assert schema['x-requires-webhook']
    assert schema['properties']['operation']['x-is-trigger']
    assert set(schema['properties']['event_type']['enum']) == set(native.WEBHOOK_EVENTS)
