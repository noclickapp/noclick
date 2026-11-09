"""Exercise the real factory against Infinity's published request/response examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import infinity_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/infinity/documented.json').read_text())
TOKEN = 'infinity-synthetic-secret-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='infinity-test', node_type='automation-infinity',
        node_data={'config': config, 'credentials': {'credential_type': 'infinity_api_token', 'api_token': TOKEN}})


def transport(monkeypatch, response):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_documented_routes_bodies_headers_and_responses(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, lambda _: httpx.Response(fixture['status'], json=fixture['response']))
    output = await node(fixture['config']).execute({})
    assert output['status'] == 'success' and output['http_status'] == fixture['status']
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method'] and request.url.path == fixture['path']
    assert request.url.host == 'app.startinfinity.com'
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.headers['X-API-Version'] == native.VERSION
    assert request.headers['Accept'] == 'application/json'
    if fixture['body'] is None:
        assert request.content == b''
    else:
        assert json.loads(request.content) == fixture['body']
    if operation.startswith('list_'):
        assert output['data'] == fixture['response']['data']
        assert output['has_more'] == fixture['response']['has_more']
        assert dict(request.url.params) == {'limit': '100', 'sort_by': 'created_at', 'sort_direction': 'desc'}
    else:
        assert output['data'] == fixture['response']
        assert not request.url.params


@pytest.mark.asyncio
async def test_cursor_filter_round_trip_one_page_and_false_values(monkeypatch):
    requests = transport(monkeypatch, {'data': [], 'has_more': True, 'after': 'next+/=', 'before': 'prev'})
    result = await node({'operation': 'list_items', 'workspace_id': '669', 'board_id': 'LA1dW8i1TTK',
        'folder_id': 'APwqfkShQuR', 'after': 'cursor+/=', 'limit': 10, 'sort_direction': 'asc'}).execute({})
    assert dict(requests[0].url.params) == {'limit': '10', 'after': 'cursor+/=', 'sort_by': 'created_at',
        'sort_direction': 'asc', 'folder_id': 'APwqfkShQuR'}
    assert result['after'] == 'next+/=' and result['has_more'] is True and len(requests) == 1
    requests = transport(monkeypatch, FIXTURES['update_item']['response'])
    config = {**FIXTURES['update_item']['config'], 'values_json': '[{"attribute_id":"attr","data":false}]'}
    config.pop('parent_id'); config.pop('folder_id')
    await node(config).execute({})
    assert json.loads(requests[0].content) == {'values': [{'attribute_id': 'attr', 'data': False}]}
    config['values_json'] = '[]'
    await node(config).execute({})
    assert json.loads(requests[1].content) == {'values': []}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 401, 403, 404, 422, 429, 500])
async def test_provider_errors_are_not_success_and_never_followed(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status,
        json={'message': 'Denied ' + TOKEN}, headers={'Location': 'https://example.test/'}))
    result = await node({'operation': 'get_profile'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'Denied [redacted]' and len(requests) == 1 and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [[], {}, {'errors': {}}, {'data': [], 'has_more': 'false'},
    {'data': [], 'has_more': True}, {'data': [1], 'has_more': False}])
async def test_malformed_and_error_envelopes_refused(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({'operation': 'list_workspaces'}).execute({})


@pytest.mark.asyncio
async def test_non_json_transport_failure_and_token_redaction(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, text='<html>Login</html>'))
    with pytest.raises(ValueError):
        await node({'operation': 'get_profile'}).execute({})
    def fail(request):
        raise httpx.ReadTimeout('private ' + TOKEN, request=request)
    transport(monkeypatch, fail)
    result = await node({'operation': 'get_profile'}).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)
    transport(monkeypatch, {'id': 1302, 'name': TOKEN})
    assert (await node({'operation': 'get_profile'}).execute({}))['data']['name'] == '[redacted]'


@pytest.mark.parametrize('changes', [
    {'operation': 'get_board', 'workspace_id': '../evil', 'board_id': 'board'},
    {'operation': 'get_board', 'workspace_id': '669', 'board_id': 'https://example.test'},
    {'operation': 'list_workspaces', 'after': 'one', 'before': 'two'},
    {'operation': 'list_workspaces', 'limit': 101},
    {'operation': 'create_item', 'workspace_id': '669', 'board_id': 'board'},
    {'operation': 'update_item', 'workspace_id': '669', 'board_id': 'board', 'item_id': 'item'},
    {'operation': 'create_board', 'workspace_id': '669', 'name': 'Board', 'user_ids_json': '[true]'},
    {'operation': 'create_folder', 'workspace_id': '669', 'board_id': 'board', 'name': 'Folder', 'attribute_ids_json': '[1]'},
    *[{**FIXTURES['create_item']['config'], 'values_json': bad} for bad in ['{}', '[{}]', '[{"attribute_id":"attr","data":1}]', '[{"attribute_id":"attr","data":NaN}]']],
])
def test_invalid_config_refused_before_network(changes):
    with pytest.raises((ValueError, ValidationError)):
        node(changes)


def test_manual_credential_defaults_and_schema_contract():
    credential = native.InfinityAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == 'infinity_api_token' and TOKEN not in repr(credential)
    for bad in ['https://example.test/token', 'Bearer token', 'a\nb']:
        with pytest.raises(ValueError):
            native.InfinityAPITokenCredential(api_token=bad)
    assert set(native.ROUTES) == set(FIXTURES) and len(native.ROUTES) == 23
    assert native.InfinityNode.connection_evidence.operation == 'list_workspaces'
