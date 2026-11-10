"""Exercise the public API and signed events using Audienceful's published examples.

Fixtures retain provider values so request construction and event parsing can be reviewed independently of schema synthesis.
"""
import hashlib
import hmac
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import audienceful_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

FIXTURES = Path(__file__).parent / 'fixtures' / 'audienceful'
KEY = 'audienceful-test-key'
HTTP_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def fixture(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())


def node(config):
    result = NodeFactory.create_node(node_id='test-audienceful', node_type='automation-audienceful',
        node_data={'config': config, 'credentials': {'credential_type': 'audienceful_api_key', 'api_key': KEY}})
    result.emit = AsyncMock()
    return result


def transport(monkeypatch, response, status=200):
    requests = []
    original = HTTP_CLIENT
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=response) if status != 204 else httpx.Response(204)
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(reply), **kwargs))
    return requests


def test_manual_connect_default_and_json_shape_validation():
    shaped, errors, _ = shape_credential('audienceful_api_key', {'api_key': KEY})
    assert not errors
    assert native.AudiencefulAPIKeyCredential.model_validate(shaped).credential_type == 'audienceful_api_key'
    for value in ['not json', '[]', 'null']:
        with pytest.raises(ValidationError):
            native.CONFIG_MODELS['upsert_person'](email='person@example.com', extra_data_json=value)
    with pytest.raises(ValidationError):
        native.CONFIG_MODELS['person_publications'](email='person@example.com', publications_json='{"id": "yes"}')


@pytest.mark.asyncio
async def test_contact_pagination_and_recognisable_evidence(monkeypatch):
    response = fixture('list-people')
    requests = transport(monkeypatch, response)
    result = await node({'operation': 'list_people', 'cursor': response['next_cursor'], 'page_size': 25}).execute({})
    assert result['data'] == response
    assert requests[0].url.path == '/v2/people'
    assert dict(requests[0].url.params) == {'cursor': response['next_cursor'], 'page_size': '25'}
    assert requests[0].headers['X-Api-Key'] == KEY
    assert native.AudiencefulNode.connection_evidence.operation == 'list_people'


@pytest.mark.asyncio
async def test_upsert_additive_tags_and_custom_fields(monkeypatch):
    response = fixture('create-person')
    requests = transport(monkeypatch, response, 201)
    result = await node({'operation': 'upsert_person', 'email': 'person@example.com',
        'tags_json': '["vip", "newsletter"]', 'publications_json': '["The Weekly"]',
        'extra_data_json': '{"plan": "pro"}'}).execute({})
    assert result['data'] == response
    assert json.loads(requests[0].content) == {'email': 'person@example.com', 'tags': ['vip', 'newsletter'],
        'publications': ['The Weekly'], 'extra_data': {'plan': 'pro'}}


@pytest.mark.asyncio
@pytest.mark.parametrize('action,path', [('delete_person','delete'), ('unsubscribe_person','unsubscribe'), ('confirm_person_opt_in','opt-in')])
async def test_body_addressing_keeps_email_out_of_url(monkeypatch, action, path):
    requests = transport(monkeypatch, fixture('create-person'))
    await node({'operation': action, 'email': 'person@example.com'}).execute({})
    assert requests[0].method == 'POST'
    assert requests[0].url.path == '/v2/people/' + path
    assert json.loads(requests[0].content) == {'email': 'person@example.com'}


@pytest.mark.asyncio
async def test_consent_map_preserves_false_and_omission(monkeypatch):
    requests = transport(monkeypatch, {})
    await node({'operation': 'person_publications', 'email': 'person@example.com', 'publications_json': '{"pub123": false}'}).execute({})
    await node({'operation': 'person_publications', 'email': 'person@example.com'}).execute({})
    assert json.loads(requests[0].content)['publications'] == {'pub123': False}
    assert 'publications' not in json.loads(requests[1].content)


@pytest.mark.asyncio
async def test_async_send_idempotency_and_no_implicit_list_signup(monkeypatch):
    requests = transport(monkeypatch, fixture('send-transactional-email'), 202)
    output = await node({'operation': 'send_transactional_email', 'email': 'person@example.com',
        'draft': 'july-newsletter', 'subject': 'Your receipt', 'idempotency_key': 'order-1234',
        'event_properties_json': '{"order_id": "1234"}', 'fields_json': '{"first_name": "Jane"}'}).execute({})
    assert output['data']['status'] == 'pending'
    assert requests[0].headers['Idempotency-Key'] == 'order-1234'
    assert json.loads(requests[0].content) == {'email': 'person@example.com', 'draft': 'july-newsletter',
        'subject': 'Your receipt', 'event_properties': {'order_id': '1234'}, 'fields': {'first_name': 'Jane'}, 'add_contact': False}


@pytest.mark.asyncio
async def test_provider_error_and_redirect_never_claim_success(monkeypatch):
    transport(monkeypatch, {'error': {'message': 'This API key is missing the required scope: people:write'}}, 403)
    with pytest.raises(ValueError, match='missing the required scope: people:write'):
        await node({'operation': 'list_people'}).execute({})
    transport(monkeypatch, {}, 302)
    with pytest.raises(ValueError, match='unexpected redirect'):
        await node({'operation': 'list_people'}).execute({})


@pytest.mark.asyncio
async def test_webhook_register_cleanup_and_manual_no_event(monkeypatch):
    requests = transport(monkeypatch, fixture('create-webhook'), 201)
    cred = {'credential_type': 'audienceful_api_key', 'api_key': KEY}
    cls = native.AudiencefulNode
    state = await cls._register_external_webhook(webhook_url='https://example.com/webhooks/audienceful',
        credential=cred, config={'operation': 'on_event', 'event_type': 'person.created'}, node_id='test')
    assert state == {'external_webhook_id': fixture('create-webhook')['id'], 'signing_secret': fixture('create-webhook')['secret']}
    assert json.loads(requests[0].content) == {'url': 'https://example.com/webhooks/audienceful', 'events': ['person.created']}
    await cls._unregister_external_webhook(credential=cred, config=state, node_id='test')
    assert requests[1].method == 'DELETE' and requests[1].url.path.endswith('/' + state['external_webhook_id'])
    assert (await node({'operation': 'on_event'}).execute({}))['status'] == 'no_event'


@pytest.mark.parametrize('event', native.EVENTS)
def test_documented_events_and_signature_reject_tampering_replay_and_wrong_secret(event):
    payload = fixture('events')[event]
    raw = json.dumps(payload).encode()
    secret = fixture('create-webhook')['secret']
    timestamp = str(int(time.time()))
    def header(ts):
        signature = hmac.new(secret.encode(), ts.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        return {'X-Audienceful-Signature': f't={ts},v1={signature}'}
    cls = native.AudiencefulNode
    config = {'event_type': event, 'signing_secret': secret}
    assert cls.verify_webhook_signature(raw, header(timestamp), config)
    assert not cls.verify_webhook_signature(raw + b' ', header(timestamp), config)
    assert not cls.verify_webhook_signature(raw, header(str(int(timestamp)-301)), config)
    assert not cls.verify_webhook_signature(raw, header(timestamp), {**config, 'signing_secret': 'wrong'})
    assert not cls.verify_webhook_signature(raw, {}, config)
    assert cls.filter_trigger_payload(payload, config)
    assert not cls.filter_trigger_payload(payload, {'event_type': 'unsupported'})
    result = cls.resolve_agent_event(cls.resolve_trigger_payload(payload, config))
    assert 'Audienceful' in result['text'] and event.replace('bulk_email.sent', 'bulk email sent') in result['text']
    assert result['conversation_key']


@pytest.mark.asyncio
@pytest.mark.parametrize('action,config,method,path,body', [
    ('get_person', {'person_id': 'jQKdwqp3YRRtTrwqUJEp7d'}, 'GET', '/people/jQKdwqp3YRRtTrwqUJEp7d', None),
    ('update_person', {'person_id': 'jQKdwqp3YRRtTrwqUJEp7d', 'notes': 'updated'}, 'PATCH', '/people/jQKdwqp3YRRtTrwqUJEp7d', {'notes':'updated'}),
    ('list_audiences', {}, 'GET', '/audiences', None),
    ('list_audience_members', {'audience_id': 'all'}, 'GET', '/audiences/all/members', None),
    ('list_fields', {}, 'GET', '/fields', None),
    ('create_field', {'name':'Plan','data_name':'plan','type':'string'}, 'POST', '/fields', {'name':'Plan','data_name':'plan','type':'string','required':False}),
    ('update_field', {'field_id':'o4i4TNZnWsq2f2ZWVqNNWY','name':'Plan'}, 'PATCH', '/fields/o4i4TNZnWsq2f2ZWVqNNWY', {'name':'Plan'}),
    ('delete_field', {'field_id':'o4i4TNZnWsq2f2ZWVqNNWY'}, 'DELETE', '/fields/o4i4TNZnWsq2f2ZWVqNNWY', None),
    ('list_publications', {}, 'GET', '/publications', None),
    ('get_publication', {'publication_id':'pub123'}, 'GET', '/publications/pub123', None),
    ('create_publication', {'name':'Newsletter'}, 'POST', '/publications', {'name':'Newsletter'}),
    ('update_publication', {'publication_id':'pub123','auto_subscribe_new':False}, 'PATCH', '/publications/pub123', {'auto_subscribe_new':False}),
    ('list_publication_subscribers', {'publication_id':'pub123'}, 'GET', '/publications/pub123/subscribers', None),
    ('list_automation_events', {}, 'GET', '/automations/events', None),
    ('trigger_automation_event', {'email':'person@example.com','event':'signed_up'}, 'POST', '/automations/event', {'email':'person@example.com','event':'signed_up','add_person':False}),
    ('get_operation', {'operation_id':'task-abc123'}, 'GET', '/operations/task-abc123', None),
    ('list_send_reports', {'search':'July'}, 'GET', '/reports', None),
])
async def test_remaining_public_routes_and_write_shapes(monkeypatch, action, config, method, path, body):
    requests = transport(monkeypatch, {})
    await node({'operation': action, **config}).execute({})
    request = requests[0]
    assert request.method == method and request.url.path == '/v2' + path
    assert (json.loads(request.content) if request.content else None) == body
    if action == 'list_send_reports':
        assert request.url.params['search'] == 'July'


@pytest.mark.parametrize('identifier', ['..', '.', 'a/b', 'with space'])
def test_opaque_ids_do_not_escape_the_resource_path(identifier):
    with pytest.raises(ValidationError):
        native.CONFIG_MODELS['get_person'](person_id=identifier)
