"""Native Unipile factory and documented JSON/multipart wire regressions."""
import json
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import unipile_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-unipile-key-42'
CREDENTIAL = {'credential_type': 'unipile_api_key', 'api_url': 'https://api1.unipile.com:13111', 'api_key': TOKEN}
CASES = json.loads((Path(__file__).parent / 'fixtures/unipile/operations.json').read_text())


def node(config):
    return NodeFactory.create_node(node_id='unipile-test', node_type='automation-unipile',
        node_data={'config': config, 'credentials': CREDENTIAL})


@pytest.fixture
def wire(monkeypatch):
    calls = []
    response = {'status': 200, 'body': {'object': 'TestResult', 'items': [], 'cursor': None}}
    def respond(request):
        calls.append(request)
        return httpx.Response(response['status'], json=response['body'])
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls, response


def form(request):
    msg = BytesParser(policy=default).parsebytes(b'Content-Type: ' + request.headers['content-type'].encode() + b'\r\n\r\n' + request.content)
    result = {}
    for part in msg.iter_parts():
        result.setdefault(part.get_param('name', header='content-disposition'), []).append(part.get_payload(decode=True).decode())
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_every_operation_native_factory_wire(wire, case):
    calls, response = wire
    response['status'] = case.get('status', 200)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(calls) == 1  # No retry or hidden discovery call on writes.
    request = calls[0]
    assert request.method == case['method']
    assert request.url.path == '/api/v1' + case['path']
    assert request.url.host == 'api1.unipile.com' and request.url.port == 13111
    assert request.headers['X-API-KEY'] == TOKEN
    assert dict(request.url.params) == case.get('query', {})
    if 'json' in case:
        assert json.loads(request.content) == case['json']
    if 'form' in case:
        assert form(request) == case['form']


@pytest.mark.asyncio
async def test_provider_rejection_preserved_and_secrets_redacted(wire):
    calls, response = wire
    response.update(status=401, body={'title': 'Invalid credentials', 'detail': 'Rejected ' + TOKEN})
    result = await node({'operation': 'list_accounts'}).execute({})
    assert result == {'status': 'error', 'http_status': 401, 'error': 'Rejected [redacted]'}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cursor_and_account_samples_preserved(wire):
    calls, response = wire
    response['body'] = {'object': 'AccountList', 'items': [{'id': 'account-1', 'name': 'My LinkedIn', 'access_token': TOKEN}], 'cursor': 'next/page==' }
    result = await node({'operation': 'list_accounts', 'cursor': 'previous/page==', 'limit': 25}).execute({})
    assert result['data']['items'] == [{'id': 'account-1', 'name': 'My LinkedIn'}]
    assert result['data']['cursor'] == 'next/page=='
    assert dict(calls[0].url.params) == {'cursor': 'previous/page==', 'limit': '25'}


@pytest.mark.parametrize('origin', ['http://api1.unipile.com:13111', 'https://evil.test', 'https://api1.unipile.com.evil.test', 'https://u:p@api1.unipile.com:13111', 'https://api1.unipile.com/api/v1', 'https://api1.unipile.com?x=y', 'https://api1.unipile.com:0', 'https://127.0.0.1:13111'])
def test_refuse_wrong_dsn(origin):
    with pytest.raises(ValidationError):
        native.UnipileAPIKeyCredential(**{**CREDENTIAL, 'api_url': origin})


def test_manual_connect_default_and_dsn_normalization():
    cred = native.UnipileAPIKeyCredential(api_key=TOKEN, api_url='api1.unipile.com:13111/')
    assert cred.credential_type == 'unipile_api_key'
    assert cred.api_url == CREDENTIAL['api_url']


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {'items': {}}, {'items': [], 'cursor': 123}, {'type': 'errors/invalid_credentials'}])
async def test_reject_invalid_list_response(wire, body):
    wire[1]['body'] = body
    with pytest.raises(ValueError):
        await node({'operation': 'list_accounts'}).execute({})


@pytest.mark.asyncio
async def test_path_identifier_is_encoded(wire):
    await node({'operation': 'get_message', 'message_id': 'a/b?c=d'}).execute({})
    assert wire[0][0].url.raw_path == b'/api/v1/messages/a%2Fb%3Fc%3Dd'


@pytest.mark.asyncio
async def test_redirect_is_never_followed(wire):
    wire[1]['status'] = 302
    result = await node({'operation': 'list_accounts'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == 302
    assert len(wire[0]) == 1
