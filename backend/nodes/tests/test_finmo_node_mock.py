"""Exercise the native factory with Finmo's verbatim published success examples."""
import base64
import json
from pathlib import Path

import httpx
import pytest

from nodes import finmo_node as native
from nodes.core.registry import NodeFactory

PUBLISHED = json.loads((Path(__file__).parent / 'fixtures/finmo/published.json').read_text())
CREDENTIAL = {'credential_type': 'finmo_api_key', 'access_key': 'test-access', 'secret_key': 'test-secret'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='finmo-test', node_type='automation-finmo',
                                   node_data={'config': config, 'credentials': CREDENTIAL})


def mock(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(PUBLISHED))
async def test_published_examples_through_native_factory(monkeypatch, operation):
    entry = PUBLISHED[operation]
    for example in entry['responses']:
        requests = mock(monkeypatch, httpx.Response(example['status'], json=example['body']))
        result = await node(entry['config']).execute({})
        assert result['status'] == 'success'
        assert result['data'] == example['body']['data']
        request = requests[0]
        assert len(requests) == 1 and request.method == entry['method']
        assert request.url.host == 'api.finmo.net'
        expected = entry['path']
        for key, value in entry['config'].items():
            expected = expected.replace('{' + key + '}', str(value))
        assert request.url.path == '/v1' + expected
        assert request.headers['Authorization'] == 'Basic ' + base64.b64encode(b'test-access:test-secret').decode()
        assert dict(request.url.params) == {k: str(entry['config'][k]).lower() if isinstance(entry['config'][k], bool) else str(entry['config'][k])
                                            for k in native.ROUTES[operation][2] if k in entry['config']}
        if 'body' in entry['config']:
            assert json.loads(request.content) == entry['config']['body']
        else:
            assert request.content == b''
        if operation.startswith('list_'):
            assert result['complete'] is False and result['page'] == entry['config']['page']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 429, 500])
async def test_rejections_are_errors_and_never_retried(monkeypatch, status):
    requests = mock(monkeypatch, httpx.Response(status, json={'success': False, 'message': 'test-secret rejected'},
                                               headers={'Location': 'https://example.test'}))
    result = await node({'operation': 'list_wallets'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert 'test-secret' not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelope_and_unexpected_shape(monkeypatch):
    mock(monkeypatch, httpx.Response(200, json={'success': False, 'message': 'Denied'}))
    assert (await node({'operation': 'list_wallets'}).execute({}))['status'] == 'error'
    mock(monkeypatch, httpx.Response(200, json={'success': True}))
    with pytest.raises(ValueError, match='unexpected data envelope'):
        await node({'operation': 'list_wallets'}).execute({})


def test_closed_routes_and_hidden_keys():
    schema = native.FinmoFullConfig.model_json_schema()
    assert len(native.ROUTES) == 22
    cred = schema['$defs']['FinmoAPIKeyCredential']['properties']
    assert all(cred[k]['ui:widget'] == 'password' for k in ('access_key', 'secret_key'))
    for config in ({'operation': 'get_customer', 'customer_id': '../other'},
                   {'operation': 'list_wallets', 'page': 0},
                   {'operation': 'create_payout', 'body': {}},
                   {'operation': 'custom_request', 'url': 'https://example.test'}):
        with pytest.raises(ValueError):
            native.FinmoNode.parse_config({'config': config, 'credentials': CREDENTIAL})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(PUBLISHED))
async def test_published_rejections_remain_failures(monkeypatch, operation):
    entry = PUBLISHED[operation]
    for example in entry['errors']:
        requests = mock(monkeypatch, httpx.Response(example['status'], json=example['body']))
        result = await node(entry['config']).execute({})
        assert result['status'] == 'error' and result['success'] is False
        assert result['http_status'] == example['status'] and len(requests) == 1
