"""Exercise the registered RAWG node against its pinned HTTP operation mapping."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import rawg_video_games_database_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from utils import ssrf

TOKEN = 'synthetic-rawg-key-42'
AUTH = {'credential_type': 'rawg_video_games_database_api_key', 'api_key': TOKEN}
TYPE = 'automation-rawg-video-games-database'
ROUTES = json.loads((Path(__file__).parent / 'fixtures/rawg-video-games-database/routes.json').read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies, policies = [], [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def respond(request):
        requests.append(request)
        assert request.url.host == 'api.rawg.io'
        assert request.url.params['key'] == TOKEN
        assert request.headers['Accept'] == 'application/json'
        return replies.pop(0)
    guarded = ssrf.guarded_async_client
    def client(**kwargs):
        policies.append(kwargs)
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return guarded(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests, replies, policies


def node(config, auth=AUTH):
    return NodeFactory.create_node(node_id='rawg-test', node_type=TYPE,
        node_data={'config': config, 'credentials': auth})


def page(**extra):
    return {'count': 1, 'results': [{'id': 3498, 'name': 'Grand Theft Auto V', 'rating': 4.5}], 'next': None, 'previous': None, **extra}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ROUTES)
async def test_each_operation_uses_exact_published_method_path_and_query(transport, operation):
    expected = ROUTES[operation]
    path, config = expected['path'], {'operation': operation}
    if '{id}' in path:
        config['id'] = '3498' if operation == 'get_game' else 4
        path = path.replace('{id}', str(config['id']))
    if '{game_pk}' in path:
        config['game_pk'] = '3498'
        path = path.replace('{game_pk}', config['game_pk'])
    listing = operation.startswith('list_')
    response = page() if listing else {'id': config['id'], 'name': 'Selected game or catalog resource'}
    transport[1].append(httpx.Response(200, json=response))
    output = await node(config).run({})
    assert output['status'] == 'success' and output['data']['results' if listing else 'id'] == (response['results'] if listing else response['id'])
    assert len(transport[0]) == len(transport[2]) == 1 and not transport[1]
    request = transport[0][0]
    assert request.method == expected['method'] and request.url.path == '/api' + path
    assert not request.content
    assert dict(request.url.params) == {'key': TOKEN, **({'page': '1', 'page_size': '20'} if listing else {})}
    assert TOKEN not in json.dumps(output)
    if listing:
        assert output['next_page'] is None and not output['has_more']


@pytest.mark.asyncio
async def test_filters_unicode_and_false_are_sent_without_dropping_or_rewriting(transport):
    config = {'operation': 'list_games', 'page': 3, 'page_size': 40, 'search': 'café + adventure',
        'search_precise': False, 'search_exact': True, 'platforms': '4,5', 'developers': 'valve-software',
        'dates': '2010-01-01,2018-12-31', 'metacritic': '80,100', 'exclude_additions': False,
        'ordering': '-released', 'platforms_count': 1}
    transport[1].append(httpx.Response(200, json=page(next='https://api.rawg.io/api/games?key=' + TOKEN + '&page=4')))
    result = await node(config).run({})
    assert result['status'] == 'success' and result['next_page'] == 4 and result['has_more']
    expected = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config.items() if k != 'operation'}
    assert dict(transport[0][0].url.params) == {**expected, 'key': TOKEN}
    assert 'next' not in result['data'] and 'previous' not in result['data'] and TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_only_one_page_is_requested_and_provider_links_are_never_followed(transport):
    transport[1].append(httpx.Response(200, json=page(next='https://untrusted.example/anything?key=' + TOKEN)))
    result = await node({'operation': 'list_games'}).execute({})
    assert result['next_page'] == 2 and len(transport[0]) == 1 and TOKEN not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 401, 403, 404, 429, 500])
async def test_errors_preserve_provider_reason_without_exposing_key_or_following_redirects(transport, status):
    transport[1].append(httpx.Response(status, json={'detail': 'RAWG rejected ' + TOKEN}, headers={'location': 'https://untrusted.example'}))
    result = await node({'operation': 'list_games'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'error': {'detail': 'RAWG rejected [redacted]'}}
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'count': 1}, {'count': -1, 'results': []}, {'count': 1, 'results': [None]}, {'count': 1, 'results': [], 'next': 5}])
async def test_invalid_pages_fail_without_reporting_success(transport, body):
    transport[1].append(httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({'operation': 'list_games'}).execute({})


@pytest.mark.asyncio
async def test_error_envelope_is_not_success(transport):
    transport[1].append(httpx.Response(200, json={'detail': 'Invalid API key'}))
    assert (await node({'operation': 'list_games'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type", [TYPE])
async def test_manual_credential_can_connect_through_the_public_operation_seam(transport, node_type):
    shaped, errors, resolved = shape_credential(AUTH['credential_type'], {'api_key': '  ' + TOKEN + '  '})
    assert not errors and resolved[0] == TYPE and shaped == {'api_key': TOKEN}
    assert native.RawgAPIKeyCredential.model_validate(shaped).model_dump() == AUTH
    transport[1].append(httpx.Response(200, json=page(count=0, results=[])))
    result = await run_node_operation(node_type=node_type, operation='list_games', arguments={}, credential_data=shaped,
        user_id='00000000-0000-4000-8000-000000000001')
    assert result['status'] == 'success' and result['data']['results'] == []
    assert native.RawgVideoGamesDatabaseNode.connection_evidence.proves == 'reachability'


@pytest.mark.parametrize('config', [
    {'operation': 'list_games', 'page': 0}, {'operation': 'list_games', 'page_size': 41},
    {'operation': 'get_game', 'id': '../other'}, {'operation': 'list_game_stores', 'game_pk': 'https://example.com'},
    {'operation': 'get_developer', 'id': 0}, {'operation': 'create_game'},
    {'operation': 'list_developers', 'search': 'unsupported'},
])
def test_invalid_or_unsupported_config_is_rejected(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize('key', ['', 'https://rawg.io/apidocs', 'has spaces', 'Bearer abc', '<token>'])
def test_invalid_manual_api_keys_are_rejected(key):
    with pytest.raises((ValueError, ValidationError)):
        native.RawgAPIKeyCredential(api_key=key)


def test_foreign_credentials_are_not_retagged():
    with pytest.raises(ValueError, match="RAWG API key"):
        node({"operation": "list_games"}, {**AUTH, "credential_type": "unrelated_api_key"})
