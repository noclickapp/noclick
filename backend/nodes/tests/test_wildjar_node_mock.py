"""Replay WildJar's saved Postman examples and test request/error boundaries."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import wildjar_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/wildjar/postman_examples.json').read_text())
TOKEN = 'wildjar-fixture-token-42'


def node(config):
    return NodeFactory.create_node(node_id='wildjar-test', node_type='automation-wildjar', node_data={
        'config': config, 'credentials': {'credential_type': 'wildjar_access_token', 'access_token': TOKEN},
    })


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_saved_postman_response_and_exact_request(monkeypatch, operation):
    fixture = FIXTURES[operation]
    for example in fixture['examples']:
        body = json.loads(example['body'])
        requests = transport(monkeypatch, httpx.Response(example['code'], content=example['body'].encode(), headers=[(h['key'], h['value']) for h in example['header']]))
        result = await node(fixture['config']).execute({})
        assert result['data'] == body['data']
        assert result['status'] == 'success'
        assert len(requests) == 1
        request = requests[0]
        assert request.url.host == 'api.trkcall.com' and request.url.scheme == 'https'
        assert request.method == fixture['method']
        assert request.url.path == '/v2' + fixture['path'].format(**fixture['config'])
        assert request.headers['authorization'] == 'Bearer ' + TOKEN
        if operation == 'send_sms':
            assert request.headers['content-type'] == 'application/javascript'
        if request.method == 'GET':
            assert not request.content
        else:
            sent = json.loads(request.content)
            expected = json.loads(example['originalRequest']['body']['raw'])
            # Normalize the saved SMS recipient's stray leading space. Empty optional
            # forceCaller is omitted, rather than turned into a different caller ID.
            expected = {k: v.strip() if k == 'target' else v for k, v in expected.items() if v != ''}
            assert sent == expected
            assert result['write_acknowledged'] and result['readback_verified'] is False
        if operation.startswith('list_'):
            assert result['complete'] is False
        if operation == 'send_sms':
            assert result['delivery_verified'] is False


@pytest.mark.parametrize('value', ['Bearer secret', 'https://example.com/key', 'secret\nheader', '<token>'])
def test_rejects_unsafe_credentials(value):
    with pytest.raises((ValueError, ValidationError)):
        native.WildJarTokenCredential(access_token=value)


def test_manual_connect_default_and_path_guard():
    assert native.WildJarTokenCredential(access_token=TOKEN).credential_type == 'wildjar_access_token'
    for value in ['../account', 'one/two', '?x=y', 'https://evil.example', '%2f']:
        with pytest.raises(ValueError):
            node({'operation': 'get_number', 'tracking_number': value})


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [
    (200, {'status': 'error', 'message': 'rejected'}),
    (200, {'status': 'ok', 'data': {}}),
    (200, {'status': 'ok', 'data': [1]}),
    (401, {'message': 'Invalid token'}),
    (429, {'message': 'Too many requests'}),
    (302, {'message': 'redirect'}),
])
async def test_error_envelopes_and_http_rejections(monkeypatch, status, body):
    requests = transport(monkeypatch, httpx.Response(status, json=body))
    with pytest.raises(ValueError):
        await node({'operation': 'list_accounts'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_account_and_resource_mismatch_rejected(monkeypatch):
    fixture = FIXTURES['get_transfer']
    body = json.loads(fixture['examples'][0]['body'])
    for field in ['id', 'account']:
        changed = {**body, 'data': {**body['data'], field: '99999'}}
        transport(monkeypatch, httpx.Response(200, json=changed))
        with pytest.raises(ValueError, match='different'):
            await node(fixture['config']).execute({})


@pytest.mark.asyncio
async def test_write_timeout_not_retried_or_claimed_success(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout('includes ' + TOKEN, request=request)
    requests = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match='inspect writes') as error:
        await node(FIXTURES['send_sms']['config']).execute({})
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_provider_errors_redact_token_and_preserve_message(monkeypatch):
    transport(monkeypatch, httpx.Response(401, json={'message': 'Invalid access token ' + TOKEN}))
    with pytest.raises(ValueError, match='Invalid access token') as error:
        await node({'operation': 'list_accounts'}).execute({})
    assert TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_invalid_json_and_redacted_output(monkeypatch):
    transport(monkeypatch, httpx.Response(200, text='<html>sign in</html>'))
    with pytest.raises(ValueError, match='invalid JSON'):
        await node({'operation': 'list_accounts'}).execute({})
    transport(monkeypatch, httpx.Response(200, json={'status': 'ok', 'data': [{'name': TOKEN}]}))
    assert TOKEN not in str(await node({'operation': 'list_accounts'}).execute({}))


@pytest.mark.asyncio
async def test_write_acknowledgment_requires_resource_identifier(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={'status': 'ok', 'data': {}}))
    with pytest.raises(ValueError, match='no write identifier'):
        await node(FIXTURES['send_sms']['config']).execute({})


@pytest.mark.asyncio
async def test_sms_list_write_cannot_cross_account(monkeypatch):
    fixture = FIXTURES['create_sms_contact_list']
    body = json.loads(fixture['examples'][0]['body'])
    body['data']['account'] = '99999'
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError, match='different account'):
        await node(fixture['config']).execute({})
