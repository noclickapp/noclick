"""Wire contracts from numverify's published OpenAPI 1.0.0 examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import numverify_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/numverify/operations.json').read_text())
TOKEN = 'numverify-test-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='numverify-test', node_type='automation-numverify',
        node_data={'config': config, 'credentials': {'credential_type': 'numverify_api_key', 'api_key': TOKEN}})


def mock_client(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        return response
    def factory(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', factory)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['operation'] + str(case['response'].get('valid', '')))
async def test_numverify_contract_examples(monkeypatch, case):
    requests = mock_client(monkeypatch, httpx.Response(200, json=case['response']))
    result = await node({'operation': case['operation'], **case['config']}).execute({})
    expected = {'countries': case['response']} if case['operation'] == 'list_supported_countries' else case['response']
    assert result == {**expected, 'status': 'success', 'http_status': 200}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'GET'
    assert request.url.scheme == 'https'
    assert request.url.host == 'apilayer.net'
    assert request.url.path == case['path']
    assert dict(request.url.params) == {'access_key': TOKEN, **case['config']}
    assert not request.content


@pytest.mark.asyncio
async def test_numverify_national_number(monkeypatch):
    requests = mock_client(monkeypatch, httpx.Response(200, json=CASES[0]['response']))
    result = await node({'operation': 'validate_phone_number', 'number': '4158586273', 'country_code': 'us'}).execute({})
    assert result['status'] == 'success'
    assert dict(requests[0].url.params) == {'access_key': TOKEN, 'number': '4158586273', 'country_code': 'US'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload,message', [
    (200, {'success': False, 'error': {'code': 101, 'type': 'invalid_access_key', 'info': 'Invalid access key'}}, 'Invalid access key'),
    (403, {'error': {'info': 'Rejected ' + TOKEN}}, 'Rejected [redacted]'),
    (429, {'error': {'type': 'usage_limit_reached'}}, 'usage_limit_reached'),
    (302, {}, 'numverify did not confirm this read'),
])
async def test_numverify_rejections(monkeypatch, status, payload, message):
    requests = mock_client(monkeypatch, httpx.Response(status, json=payload, headers={'Location': 'https://other.test'}))
    result = await node({'operation': 'list_supported_countries'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'error': message}
    assert len(requests) == 1
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,payload', [
    ('list_supported_countries', {}), ('list_supported_countries', {'US': {}}),
    ('list_supported_countries', {'US': {'country_name': 'United States', 'dialling_code': 1}}),
    ('validate_phone_number', {}), ('validate_phone_number', {'valid': 'false'}),
    ('validate_phone_number', []),
])
async def test_numverify_unexpected_shapes(monkeypatch, operation, payload):
    mock_client(monkeypatch, httpx.Response(200, json=payload))
    result = await node({'operation': operation, **({'number': '12345'} if operation == 'validate_phone_number' else {})}).execute({})
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_numverify_transport_and_non_json(monkeypatch):
    mock_client(monkeypatch, httpx.RequestError('https://apilayer.net/api?access_key=' + TOKEN))
    result = await node({'operation': 'list_supported_countries'}).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)
    mock_client(monkeypatch, httpx.Response(502, text='<html>error</html>'))
    assert (await node({'operation': 'list_supported_countries'}).execute({}))['status'] == 'error'


@pytest.mark.parametrize('config', [
    {'operation': 'validate_phone_number', 'number': ''},
    {'operation': 'validate_phone_number', 'number': 'https://example.com'},
    {'operation': 'validate_phone_number', 'number': '123', 'country_code': 'USA'},
    {'operation': 'validate_phone_number', 'number': '+14158586273', 'country_code': 'US'},
    {'operation': 'list_supported_countries', 'url': 'https://other.test'},
])
def test_numverify_input_validation(config):
    with pytest.raises(ValidationError):
        native.NumverifyFullConfig(config=config)


def test_numverify_manual_credential_and_evidence():
    credential = native.NumverifyAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == 'numverify_api_key'
    assert native.NumverifyNode.connection_evidence.operation == 'list_supported_countries'
    assert native.NumverifyNode.connection_evidence.proves == 'reachability'
    with pytest.raises(ValidationError):
        native.NumverifyAPIKeyCredential(credential_type='other', api_key=TOKEN)


@pytest.mark.asyncio
async def test_numverify_does_not_echo_access_key(monkeypatch):
    mock_client(monkeypatch, httpx.Response(200, json={'valid': True, 'carrier': TOKEN, 'access_key': TOKEN}))
    result = await node({'operation': 'validate_phone_number', 'number': '14158586273'}).execute({})
    assert result['status'] == 'success' and TOKEN not in str(result)
