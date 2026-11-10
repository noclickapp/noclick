"""Official v5 response examples exercised through the native node factory."""
import json
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from nodes import bkper_node as mod
from nodes.core.registry import NodeFactory

RESPONSES = json.loads((Path(__file__).parent / 'fixtures/bkper/responses.json').read_text())
AUTH = {'credential_type': 'google_oauth', 'access_token': 'fixture-access-token'}
BOOK = 'string'
URL = 'https://fixture.hooks.example.test/bkper/events'


@pytest.fixture
def ensure_native_db_pool():
    yield


def config_for(name):
    spec = mod.OPERATIONS[name]
    cfg = {'operation': name}
    for p in spec['parameters']:
        key = mod.PARAM_NAMES.get(p['name'], p['name'])
        if p['in'] == 'body':
            model = mod.BODY_MODELS[p['name']]
            example = RESPONSES[name]
            if p['name'] == 'Transaction':
                example = example.get('transaction', example)
            cfg['body'] = {k: v for k, v in example.items() if k in model.model_fields}
            for k in ('creditAccount', 'debitAccount'):
                if k in cfg['body']:
                    cfg['body'][k] = {'id': example[k]['id']}
            if 'parent' in cfg['body']:
                cfg['body']['parent'] = {'id': 'string'}
            if 'groups' in cfg['body']:
                cfg['body']['groups'] = []
        elif p.get('required'):
            cfg[key] = 1 if p.get('type') == 'integer' else 'string'
    return cfg


def node(config):
    return NodeFactory.create_node(node_id='bkper-unit', node_type='automation-bkper',
        node_data={'config': config, 'credentials': deepcopy(AUTH)})


@pytest.mark.asyncio
@pytest.mark.parametrize('name', mod.OPERATIONS)
async def test_official_response_and_exact_wire_contract(monkeypatch, name):
    cfg = config_for(name)
    calls = []
    spec = mod.OPERATIONS[name]
    async def send(request):
        calls.append(request)
        assert request.url.host == 'api.bkper.app'
        assert request.headers['authorization'] == 'Bearer fixture-access-token'
        assert request.method == spec['method']
        assert request.url.path == spec['path'].replace('{bookId}', 'string').replace('{id}', str(cfg.get('resource_id', 'string')))
        assert 'fixture-access-token' not in str(request.url)
        sent = json.loads(request.content) if request.content else None
        assert sent == cfg.get('body')
        for p in spec['parameters']:
            if p['in'] == 'query' and p.get('required'):
                assert request.url.params[p['name']] == cfg[p['name']]
        return httpx.Response(200, json=RESPONSES[name])
    original = httpx.AsyncClient
    monkeypatch.setattr(mod.httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(send)))
    assert await node(cfg).execute({}) == RESPONSES[name]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_http_and_error_envelope_failures(monkeypatch):
    for status, body in [(401, {'error': 'Unauthenticated'}), (429, {'error': 'Quota exceeded'}), (403, {'error': {'message': 'Access denied to book'}}), (200, {'error': 'Denied'})]:
        async def send(request):
            return httpx.Response(status, json=body)
        original = httpx.AsyncClient
        with monkeypatch.context() as m:
            m.setattr(mod.httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(send)))
            with pytest.raises((httpx.HTTPStatusError, ValueError)) as raised:
                await node({'operation': 'list_books'}).execute({})
            if status == 403:
                assert 'Access denied to book' in str(raised.value)


def test_manual_credential_and_invalid_inputs():
    assert mod.BkperOAuthCredential(access_token='fixture-access-token').credential_type == 'google_oauth'
    for token in ('https://example.test/key', '<token>'):
        with pytest.raises(ValueError):
            mod.BkperOAuthCredential(access_token=token)
    for operation, body in [('create_transaction', {'date': '2024-01-15'}), ('update_account', {'name': 'Savings'})]:
        with pytest.raises(ValueError):
            node({'operation': operation, 'book_id': BOOK, 'body': body})
    with pytest.raises(ValueError):
        mod._id('../another-book')


@pytest.mark.asyncio
async def test_registration_unregistration_and_book_picker(monkeypatch):
    request = AsyncMock(side_effect=[{'id': 'app'}, {'id': 'app'}, {'items': []}, {'id': 'installed'}, {}])
    monkeypatch.setattr(mod.BkperNode, '_request', request)
    config = {'operation': 'on_book_event', 'book_id': BOOK}
    registered = await mod.BkperNode._register_external_webhook(webhook_url=URL, credential=AUTH, config=config, node_id='unit')
    assert registered == {'external_webhook_id': 'installed'}
    app_call = request.call_args_list[1]
    assert app_call.args[1:3] == ('PUT', '/v5/apps')
    assert app_call.kwargs['body']['webhookUrl'] == URL
    assert app_call.kwargs['body']['webhookUrlDev'] == URL
    assert app_call.kwargs['body']['apiVersion'] == 'v5'
    assert set(app_call.kwargs['body']['events']) == set(mod.EVENT_TYPES)
    assert request.call_args_list[3].kwargs['body'] == {'agentId': 'noclick-unit'}
    await mod.BkperNode._unregister_external_webhook(credential=AUTH, config={**config, **registered}, node_id='unit')
    assert request.call_args.args[1:3] == ('DELETE', '/v5/books/string/integrations/installed')
    request.side_effect = None
    request.return_value = RESPONSES['list_books']
    choices = await mod.BkperNode.load_field_options('book_id', AUTH)
    assert choices['options'][0] == {'value': 'string', 'label': 'string'}


def test_signed_delivery_identity_and_negative_cases(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(mod._GOOGLE_KEYS, 'get_signing_key_from_jwt', lambda token: SimpleNamespace(key=key.public_key()))
    claims = {'iss': 'https://accounts.google.com', 'aud': URL, 'iat': int(time.time()), 'exp': int(time.time()) + 300,
              'sub': 'fixture-service', 'email': mod.SERVICE_ACCOUNT, 'email_verified': True}
    body = json.dumps(RESPONSES['list_events']['items'][0]).encode()
    def verify(overrides=None):
        signed = jwt.encode({**claims, **(overrides or {})}, key, algorithm='RS256', headers={'kid': 'fixture'})
        return mod.BkperNode.verify_webhook_signature(body, {'Authorization': 'Bearer ' + signed}, {'webhook_url': URL})
    assert verify()
    for changes in ({'aud': 'https://attacker.test'}, {'iss': 'https://attacker.test'}, {'email': 'attacker@example.test'},
                    {'email_verified': False}, {'exp': 1}):
        assert not verify(changes)
    assert not mod.BkperNode.verify_webhook_signature(body, {}, {'webhook_url': URL})
    assert not mod.BkperNode.verify_webhook_signature(body, {'authorization': 'Bearer broken'}, {'webhook_url': URL})


def test_every_documented_event_has_human_context_and_book_isolation():
    # Payload example is copied from listEvents; type values are its published enum.
    for event_type in mod.EVENT_TYPES:
        event = deepcopy(RESPONSES['list_events']['items'][0])
        event['type'] = event_type
        assert mod.BkperNode.filter_trigger_payload(event, {'book_id': BOOK})
        assert not mod.BkperNode.filter_trigger_payload(event, {'book_id': 'another-book'})
        resolved = mod.BkperNode.resolve_agent_event(event)
        assert event_type.replace('_', ' ').lower() in resolved['text']
        assert 'Event ID: string' in resolved['text']
        assert 'book ID: string' in resolved['text']
        assert resolved['conversation_key'] == 'bkper:string'


@pytest.mark.asyncio
async def test_oauth_refresh_uses_the_shared_choke_point(monkeypatch):
    import nodes.core.oauth_refresh as refresh
    stub = AsyncMock(return_value={**AUTH, 'access_token': 'renewed'})
    monkeypatch.setattr(refresh, 'freshen_oauth_credential', stub)
    result = await mod.BkperNode.freshen_credential({**AUTH, 'refresh_token': 'fixture-refresh'})
    assert result['access_token'] == 'renewed'
    assert stub.call_args.kwargs['provider'] == 'google'


def test_delivery_credentials_do_not_escape_into_output():
    example = deepcopy(RESPONSES['list_events']['items'][0])
    example['_webhook'] = {'headers': {'bkper-oauth-token': 'secret', 'authorization': 'Bearer secret'}}
    assert '_webhook' not in mod.BkperNode.resolve_trigger_payload(example, {})


def test_canvas_picker_metadata_is_not_api_input():
    parsed = node({'operation': 'get_book', 'book_id': BOOK, 'book_id__label': 'Main book', 'credentialIds': {}}).config.config
    assert parsed.model_dump(exclude_none=True) == {'operation': 'get_book', 'book_id': BOOK}
    with pytest.raises(ValueError):
        node({'operation': 'create_account', 'book_id': BOOK, 'body': {'name': 'Bank', 'unsupported': 'value'}})
