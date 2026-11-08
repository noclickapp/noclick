"""Exercise native factory requests at Heartbeat's HTTP boundary.
Synthetic cases cover each route and error handling without an account.
"""
import json
from pathlib import Path
import httpx
import pytest
from nodes import heartbeat_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/heartbeat/requests.json').read_text())
TOKEN = 'synthetic-heartbeat-api-key'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='heartbeat-test', node_type='automation-heartbeat',
        node_data={'config': config, 'credentials': {'credential_type': 'heartbeat_api_key', 'api_key': TOKEN}})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_published_request_contract(monkeypatch, operation):
    case = CASES[operation]
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json=case['response'])
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    result = await node(case['config']).execute({})
    assert result['success'] and result['data'] == case['response']
    request, = requests
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.url.host == 'api.heartbeat.chat'
    expected_path = case['path']
    for key, value in case['config'].items():
        expected_path = expected_path.replace('{' + key + '}', str(value))
    assert request.method == case['method'] and request.url.path == '/v0' + expected_path
    method, _, paths, queries, body, _, _ = native.ROUTES[operation]
    expected = {k: v for k, v in case['config'].items() if k not in ['operation', *paths, *queries]}
    assert (json.loads(request.content) if body else {}) == expected
    assert dict(request.url.params) == {k: str(case['config'][k]) for k in queries if k in case['config']}
    assert TOKEN not in str(result)
    assert result.get('write_acknowledged', False) == (method != 'GET')


@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload', [(401, {'error': 'denied'}), (429, {}), (200, {'error': 'bad'}), (200, 'bad'), (200, [1])])
async def test_failure_never_claims_success(monkeypatch, status, payload):
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload)), **kw))
    if status == 200:
        with pytest.raises(ValueError):
            await node({'operation': 'list_users'}).execute({})
    else:
        result = await node({'operation': 'list_users'}).execute({})
        assert result['success'] is False and result['http_status'] == status


@pytest.mark.parametrize('config', [
    {'operation': 'get_user', 'userID': '../users'},
    {'operation': 'create_user', 'email': 'bad', 'name': 'Name', 'roleID': 'bad'},
    {'operation': 'list_documents', 'limit': 101},
    {'operation': 'create_comment', 'text': 'Hello', 'threadID': '11111111-1111-4111-8111-111111111111'},
])
def test_invalid_inputs_rejected(config):
    assert not native.HeartbeatNode.validate_config({'config': config})['valid']


@pytest.mark.asyncio
async def test_query_cursor_and_secret_redaction(monkeypatch):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json=[{'title': TOKEN}])
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(reply), **kw))
    cursor = '11111111-1111-4111-8111-111111111111'
    result = await node({'operation': 'list_documents', 'startingAfter': cursor, 'limit': 10}).execute({})
    assert dict(requests[0].url.params) == {'startingAfter': cursor, 'limit': '10'}
    assert result['data'] == [{'title': '[redacted]'}]
