"""Offline request/response regressions for all ImageRouter operations."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import imagerouter_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/imagerouter/operations.json').read_text())
TOKEN = 'imagerouter-synthetic-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='imagerouter-test', node_type='automation-imagerouter',
        node_data={'config': config, 'credentials': credentials or {'credential_type': 'imagerouter_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_operation_wire_contract(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=fixture['response']))
    result = await node(fixture['config']).execute({})
    assert result == {'status': 'success', 'http_status': 200, 'data': fixture['response']}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method'] and request.url.path == fixture['path']
    assert request.url.host == 'api.imagerouter.io'
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.headers['Accept'] == 'application/json'
    assert dict(request.url.params) == ({'by_api_key': 'true'} if operation == 'list_api_key_usage' else {})
    if fixture['method'] == 'GET':
        assert not request.content
    else:
        body = json.loads(request.content)
        assert body['model'] == fixture['config']['model']
        assert 'operation' not in body and 'api_key' not in body
        if operation.startswith('generate_'):
            assert body['response_format'] == 'url' and body['size'] == 'auto'
        if 'image' in fixture['config']:
            assert body['image'] == fixture['config']['image']
        if operation == 'describe_image':
            assert body['messages'][0]['content'] == [
                {'type': 'text', 'text': 'What is in this image?'},
                {'type': 'image_url', 'image_url': {'url': 'https://example.com/photo.jpg'}},
            ]
        if operation == 'create_chat_completion':
            assert body['messages'] == fixture['config']['messages']
            assert 'stream' not in body
        if operation == 'create_response':
            assert body['input'] == 'Hello!' and 'stream' not in body


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 422, 429, 500])
async def test_errors_redact_key_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={'error': {'message': 'Rejected ' + TOKEN}}))
    result = await node(FIXTURES['generate_image']['config']).execute({})
    assert result['status'] == 'error' and result['status_code'] == status
    assert 'Rejected' in result['error'] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text='<html>login</html>'), httpx.Response(200, json={'error': {'message': 'Invalid key'}})])
async def test_non_json_and_error_envelope_fail(monkeypatch, response):
    transport(monkeypatch, lambda _: response)
    assert (await node({'operation': 'get_credits'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_connection_evidence_is_account_usage_and_rejects_missing_data(monkeypatch):
    evidence = native.ImagerouterNode.connection_evidence
    assert evidence.operation == 'list_api_key_usage' and evidence.proves == 'account'
    transport(monkeypatch, lambda _: httpx.Response(200, json={'remaining_credits': '0', 'credit_usage': '0', 'total_deposits': '0'}))
    assert (await node({'operation': evidence.operation}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_timeout_is_not_retried(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout('Timed out', request=request)
    requests = transport(monkeypatch, timeout)
    result = await node(FIXTURES['generate_video']['config']).execute({})
    assert result['status'] == 'error' and 'before retrying' in result['error']
    assert len(requests) == 1


def test_manual_credential_default_and_secret_cleaning():
    shaped, errors, _ = shape_credential('imagerouter_api_key', {'api_key': '  ' + TOKEN + '  '})
    assert not errors and shaped['api_key'] == TOKEN
    assert native.ImagerouterAPIKeyCredential.model_validate(shaped).credential_type == 'imagerouter_api_key'


@pytest.mark.parametrize('key', ['https://imagerouter.io/api-keys', 'Bearer some-key', 'some\nkey', '<token>'])
def test_refuse_bad_credentials(key):
    with pytest.raises((ValidationError, ValueError)):
        native.ImagerouterAPIKeyCredential(api_key=key)


@pytest.mark.parametrize('config', [
    {'operation': 'generate_image', 'model': ''},
    {'operation': 'generate_video', 'model': 'ir/test-video', 'seconds': 61},
    {'operation': 'generate_image', 'model': 'test/test', 'response_format': 'b64_json'},
    {'operation': 'create_chat_completion', 'model': 'text/model', 'messages': []},
    {'operation': 'get_credits', 'host': 'https://evil.test'},
])
def test_invalid_request_configs(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_provider_does_not_leak_unexpected_inline_media(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={'data': [{'b64_json': 'unusable-inline-media'}]}))
    result = await node(FIXTURES['generate_image']['config']).execute({})
    assert result['status'] == 'error' and 'unusable-inline-media' not in str(result)


@pytest.mark.asyncio
async def test_image_data_uri_is_forwarded_in_json(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=FIXTURES['generate_image']['response']))
    config = {**FIXTURES['generate_image_from_image']['config'], 'image': 'data:image/png;base64,iVBORw0KGgo='}
    await node(config).execute({})
    assert json.loads(requests[0].content)['image'] == config['image']
