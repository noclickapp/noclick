"""Exercise kvCORE requests against its collection's own saved response bodies.

These tests pin serialization, untouched response data and the manual connection
read. The error case also uses a saved provider response; timeouts have no response.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import kvcore_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/kvcore/saved_examples.json').read_text())
TOKEN = 'test-kvcore-token-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(
        node_id='kvcore-test', node_type='automation-kvcore',
        node_data={'config': config, 'credentials': credential or {
            'credential_type': 'kvcore_api_token', 'api_token': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(status, content=body, headers={'Content-Type': 'application/json'})

    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_saved_collection_example(monkeypatch, operation):
    case = EXAMPLES[operation]
    requests = transport(monkeypatch, case['body'], case['status'])
    out = await node(case['config']).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case['method']
    assert str(req.url) == 'https://api.kvcore.com' + case['path']
    assert req.headers['authorization'] == 'Bearer ' + TOKEN
    assert req.headers['content-type'] == 'application/json'
    expected_body = case['request_body']
    assert json.loads(req.content) == expected_body if expected_body is not None else not req.content
    assert out == {'status': 'success', 'operation': operation, 'http_status': case['status'],
                   'data': json.loads(case['body']) if case['body'] else None}
    assert TOKEN not in str(out)


@pytest.mark.asyncio
async def test_connection_read_preserves_pagination(monkeypatch):
    case = EXAMPLES['list_users']
    requests = transport(monkeypatch, case['body'])
    out = await node({'operation': native.KvcoreNode.connection_evidence.operation}).execute({})
    assert requests[0].method == 'GET'
    assert out['data']['data'][0]['email'] == 'myagent@insiderealestate.com'
    assert out['data']['current_page'] == 1
    assert 'next_page_url' in out['data']


@pytest.mark.parametrize('value', ['', 'Bearer abc', 'https://example.com/token', '<token>', 'abc\r\nxyz'])
def test_reject_invalid_token(value):
    with pytest.raises((ValueError, ValidationError)):
        native.KvcoreApiToken(api_token=value)


def test_manual_credential_has_default_type():
    credential = native.KvcoreApiToken(api_token='  ' + TOKEN + '  ')
    assert credential.credential_type == 'kvcore_api_token'
    assert credential.api_token == TOKEN
    assert set(native.KvcoreApiToken.model_json_schema()['required']) == {'api_token'}


@pytest.mark.parametrize('operation,field', [('delete_contact', 'contact_id'), ('get_note', 'action_id'),
                                           ('get_user', 'user_id')])
def test_reject_invalid_path_id(operation, field):
    config = {**EXAMPLES[operation]['config'], field: '../other'}
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.asyncio
async def test_saved_provider_error_is_not_success(monkeypatch):
    case = json.loads((Path(__file__).parent / 'fixtures/kvcore/error_example.json').read_text())
    transport(monkeypatch, case['body'], case['status'])
    out = await node({'operation': 'list_users'}).execute({})
    assert out['status'] == 'error'
    assert out['http_status'] == case['status']
    assert out['error'] == json.loads(case['body'])['message']
    assert TOKEN not in str(out)


@pytest.mark.asyncio
async def test_timeout_is_not_retried(monkeypatch):
    calls = []

    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout('timeout', request=request)

    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(fail), **kw))
    out = await node(EXAMPLES['add_note']['config']).execute({})
    assert out['status'] == 'error'
    assert len(calls) == 1
