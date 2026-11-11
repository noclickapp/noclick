"""SignWell request mapping and documented response regressions; no live API calls."""
import copy
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import signwell_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/signwell/published_responses.json').read_text())
TOKEN = 'signwell-test-private-key'
EVENTS = json.loads((Path(__file__).parent / 'fixtures/signwell/webhook_events.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='signwell-test', node_type='automation-signwell',
        node_data={'config': config, 'credentials': credentials or {'credential_type': 'signwell_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, status, body=None, content=None, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        if content is not None:
            return httpx.Response(status, content=content, headers=headers)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_one_published_operation_per_request(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, fixture['http_status'], fixture['response'])
    result = await node(fixture['config']).execute({})
    assert result['status'] == 'success'
    assert result['http_status'] == fixture['http_status']
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == 'www.signwell.com' and request.url.scheme == 'https'
    assert request.method == fixture['method'] and request.url.path == fixture['path']
    assert request.headers['X-Api-Key'] == TOKEN
    assert 'authorization' not in request.headers
    assert dict(request.url.params) == fixture['params']
    assert TOKEN not in str(result)
    if operation == 'create_template':
        body = json.loads(request.content)
        assert body['fields'][0][0]['placeholder_id'] == '1'
        assert 'recipient_id' not in body['fields'][0][0]
        assert body['draft'] is True
    elif operation == 'create_document':
        body = json.loads(request.content)
        assert body['fields'][0][0]['recipient_id'] == '1'
        assert body['draft'] is True
        assert 'placeholder_name' not in body['recipients'][0]
    elif operation == 'create_document_from_template':
        body = json.loads(request.content)
        assert body['template_id'] == fixture['config']['template_id']
        assert body['recipients'][0]['placeholder_name'] == 'Client'
    elif operation == 'update_authentication':
        assert 'example-passcode' not in str(result)
        assert json.loads(request.content)['recipients'][0]['passcode'] == 'example-passcode'
    elif operation in ['update_template', 'update_recipients', 'create_webhook']:
        body = json.loads(request.content)
        for key, value in fixture['config'].items():
            if key != 'operation' and not key.endswith('_id'):
                assert body[key] == value
    elif operation == 'get_me':
        assert result['data']['email'] == fixture['response']['user']['email']
        assert result['data']['name'] == fixture['response']['user']['name']
    if fixture['method'] == 'GET':
        assert 'request_acknowledged' not in result
    elif fixture['method'] == 'DELETE':
        assert result['deletion_acknowledged'] is True
    else:
        assert result['request_acknowledged'] is True
        assert 'delivery_verified' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 422, 429, 500])
async def test_provider_failure_never_looks_successful(monkeypatch, status):
    requests = transport(monkeypatch, status, {'message': f'Not valid authorization token {TOKEN}'})
    result = await node({'operation': 'get_me'}).execute({})
    assert len(requests) == 1
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['message'] == 'Not valid authorization token [redacted]'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {}, {'user': {'email': 'person@example.com'}}, {'error': 'bad'}, {'errors': ['bad']}])
async def test_missing_identity_or_error_envelope_cannot_prove_connection(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises(ValueError):
        await node({'operation': 'get_me'}).execute({})


@pytest.mark.asyncio
async def test_passcodes_and_api_keys_are_removed_from_output(monkeypatch):
    transport(monkeypatch, 200, {'id': 'doc', 'api_key': TOKEN, 'recipients': [{'passcode': 'private-passcode'}], 'name': TOKEN})
    result = await node({'operation': 'get_document', 'document_id': 'doc'}).execute({})
    assert TOKEN not in str(result) and 'private-passcode' not in str(result)
    assert result['data']['name'] == '[redacted]'


@pytest.mark.asyncio
@pytest.mark.parametrize('identifier', ['../me', 'doc?x=1', 'doc#secret', 'doc/path', '..'])
async def test_path_injection_never_reaches_transport(monkeypatch, identifier):
    requests = transport(monkeypatch, 200, {})
    with pytest.raises(ValueError):
        await node({'operation': 'get_document', 'document_id': identifier}).execute({})
    assert not requests


@pytest.mark.asyncio
async def test_html_is_not_an_account_response(monkeypatch):
    transport(monkeypatch, 200, content=b'<html>login</html>', headers={'content-type': 'text/html'})
    with pytest.raises(ValueError, match='bounded JSON'):
        await node({'operation': 'get_me'}).execute({})


def test_credentials_and_template_fields_are_typed():
    credential = native.SignwellAPIKeyCredential(api_key='  '+TOKEN+'  ')
    assert credential.api_key == TOKEN
    with pytest.raises(ValidationError):
        native.SignwellAPIKeyCredential(credential_type='other_key', api_key=TOKEN)
    with pytest.raises(ValidationError):
        native.SignwellAPIKeyCredential(api_key='https://example.com/key')
    with pytest.raises(ValidationError):
        native.TemplateField(x=1,y=2,page=1,recipient_id='1',type='signature')
    assert native.SignwellNode.connection_evidence.identity_operation == 'get_me'
    with pytest.raises(ValidationError) as invalid:
        native.SignwellFullConfig.model_validate({'config': {'operation': 'get_me'},
            'credentials': {'credential_type': 'other_key', 'api_key': TOKEN}})
    assert TOKEN not in str(invalid.value)


@pytest.mark.asyncio
async def test_trigger_registers_and_unregisters_using_documented_hooks(monkeypatch):
    fixture = FIXTURES['create_webhook']
    requests = transport(monkeypatch, 201, fixture['response'])
    config = {'operation': 'on_event', 'event_type': 'document_completed',
              'api_application_id': '3fa54438-5bd9-405a-9d7f-89dd47c80dc4'}
    extra = await native.SignwellNode._register_external_webhook(
        webhook_url='https://example.com/webhook', credential={'api_key': TOKEN}, config=config, node_id='test')
    assert extra == {'external_webhook_id': fixture['response']['id'], 'signing_secret': fixture['response']['id']}
    assert requests[0].method == 'POST' and requests[0].url.path == '/api/v1/hooks'
    assert requests[0].headers['X-Api-Key'] == TOKEN
    assert json.loads(requests[0].content) == {'callback_url': 'https://example.com/webhook',
        'api_application_id': config['api_application_id']}
    assert native.SignwellNode.registration_fingerprint_fields(config) == {'api_application_id': config['api_application_id']}
    persisted = native.SignwellOnEventConfig.model_validate({**config, **extra}).model_dump()
    assert persisted['signing_secret'] == fixture['response']['id']
    requests = transport(monkeypatch, 204)
    await native.SignwellNode._unregister_external_webhook(
        credential={'api_key': TOKEN}, config=persisted, node_id='test')
    assert requests[0].method == 'DELETE'
    assert requests[0].url.path == '/api/v1/hooks/' + fixture['response']['id']


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'message': TOKEN}), (201, {}), (201, [])])
async def test_trigger_registration_failures_raise_without_disclosing_key(monkeypatch, status, body):
    transport(monkeypatch, status, body)
    with pytest.raises(ValueError) as error:
        await native.SignwellNode._register_external_webhook(webhook_url='https://example.com/webhook',
            credential={'api_key': TOKEN}, config={}, node_id='test')
    assert TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_trigger_teardown_does_not_silently_skip_missing_credentials(monkeypatch):
    requests = transport(monkeypatch, 204)
    with pytest.raises(ValueError, match='Connect a SignWell'):
        await native.SignwellNode._unregister_external_webhook(
            credential=None, config={'external_webhook_id': 'registered-hook'}, node_id='test')
    assert not requests


@pytest.mark.parametrize('kind', native.SIGNWELL_EVENTS)
def test_documented_events_reach_agent_with_resource_identity(kind):
    # Event Data documents the standard, template and SMS envelopes. Events documents each type.
    sample = 'template_available' if kind.startswith('template_') else (
        'document_sms_failed' if kind.startswith('document_sms_') else 'document_viewed')
    payload = copy.deepcopy(EVENTS[sample]['body'])
    payload['event']['type'] = kind
    if kind not in {'document_viewed', 'document_declined', 'document_signed'}:
        payload['event'].pop('related_signer', None)
    if kind == 'document_sms_opted_out':
        payload['data']['object']['recipients'][0]['sms']['delivery_status'] = 'suppressed'
    config = {'operation': 'on_event', 'event_type': kind, 'signing_secret': '3ca1189b-ae29-4a9e-878d-5c53dee86987'}
    message = f"{kind}@{payload['event']['time']}".encode()
    payload['event']['hash'] = hmac.new(config['signing_secret'].encode(), message, hashlib.sha256).hexdigest()
    body = json.dumps(payload).encode()
    assert native.SignwellNode.verify_webhook_signature(body, {}, config)
    assert not native.SignwellNode.verify_webhook_signature(body, {}, {**config, 'signing_secret': 'wrong'})
    for field, value in [('type', 'document_error'), ('time', 1), ('hash', 'bad')]:
        altered = copy.deepcopy(payload)
        altered['event'][field] = value if value != payload['event'][field] else 'other'
        assert not native.SignwellNode.verify_webhook_signature(json.dumps(altered).encode(), {}, config)
    assert native.SignwellNode.filter_trigger_payload(payload, config)
    assert not native.SignwellNode.filter_trigger_payload(payload, {**config, 'event_type': 'other'})
    output = native.SignwellNode.resolve_trigger_payload(payload, config)
    agent = native.SignwellNode.resolve_agent_event(output)
    assert payload['data']['object']['id'] in agent['text']
    assert payload['data']['object']['name'] in agent['title']
    assert payload['data']['account_id'] in agent['conversation_key']
    assert kind.replace('_', ' ') in agent['text']
    assert config['signing_secret'] not in agent['text']
    if sample == 'document_viewed':
        assert 'Please complete this example agreement' in agent['text']
    if kind in {'document_viewed', 'document_declined', 'document_signed'}:
        assert 'Christian Jordan' in agent['text']
    if sample == 'document_sms_failed':
        assert 'Jane Doe' in agent['text']


@pytest.mark.parametrize('body', [b'null', b'[]', b'{}', b'bad', b'{"event":null}',
    b'{"event":{"type":"document_completed","time":true,"hash":"x"}}'])
def test_signature_fails_closed_for_malformed_payload(body):
    assert not native.SignwellNode.verify_webhook_signature(body, {}, {'signing_secret': 'hook-id'})
    assert not native.SignwellNode.verify_webhook_signature(body, {}, {})


@pytest.mark.asyncio
async def test_manual_trigger_run_never_invents_an_event(monkeypatch):
    requests = transport(monkeypatch, 200, {})
    result = await node({'operation': 'on_event'}).execute({'unrelated': 'data'})
    assert result['status'] == 'no_event'
    assert native.SignwellNode.resolve_agent_event(result) is None
    assert not requests
