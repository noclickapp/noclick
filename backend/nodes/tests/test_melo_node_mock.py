"""Melo request boundaries and documented response parsing, without an account."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import melo_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-melo-key-42'
ID = '42c930b0-7f22-4ec5-9937-e918c7846ce8'
FIXTURES = Path(__file__).parent / 'fixtures/melo'
CONTRACT_ROUTES = json.loads((FIXTURES / 'routes.json').read_text())['routes']
DOCUMENTED = json.loads((FIXTURES / 'documented.json').read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='melo-test', node_type='automation-melo', node_data={
        'config': config, 'credentials': {'credential_type': 'melo_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(CONTRACT_ROUTES))
async def test_melo_all_operations_exact_method_path_auth_and_payload(monkeypatch, operation):
    method, path = CONTRACT_ROUTES[operation]
    cfg = {'operation': operation}
    if '{id}' in path:
        cfg['id'] = ID
    if method in {'POST', 'PUT'}:
        cfg.update(title='Paris apartments', propertyTypes=[0], transactionType=0,
            notificationEnabled=False, budgetMax=500000)
    if operation == 'list_points_of_interest':
        cfg.update(facilities=['school', 'parking'], lat=48.8803424, lon=2.333215, radius=0.5)
    body = {'hydra:member': [{'title': 'My saved search', '@id': '/searches/' + ID}],
        'hydra:view': {'hydra:next': '/searches?page=2'}} if operation in native.COLLECTIONS else {'title': 'Paris apartments'}
    status = 201 if method == 'POST' else 204 if method == 'DELETE' else 200
    requests = transport(monkeypatch, body, status)
    result = await node(cfg).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path.replace('{id}', ID)
    assert req.url.host == 'api.stream.estate' and req.headers['X-API-KEY'] == TOKEN
    assert TOKEN not in str(result)
    if method in {'POST', 'PUT'}:
        assert json.loads(req.content) == {k: v for k, v in cfg.items() if k not in {'operation', 'id'}}
    if operation == 'list_points_of_interest':
        assert req.url.params.get_list('facilities[]') == ['school', 'parking']
    if operation in native.COLLECTIONS:
        assert result['items'] == body['hydra:member']
        assert result['next_page'] == '/searches?page=2'


@pytest.mark.asyncio
async def test_melo_documented_arrays_false_zero_and_provider_page(monkeypatch):
    requests = transport(monkeypatch, {'hydra:member': [], 'hydra:view': {}})
    result = await node({'operation': 'list_properties', 'propertyTypes': [0, 1], 'furnished': False,
        'transactionType': 0, 'page': 2, 'itemsPerPage': 30}).execute({})
    assert result['items'] == []
    assert requests[0].url.params.get_list('propertyTypes[]') == ['0', '1']
    assert dict(requests[0].url.params)['furnished'] == 'false'
    assert dict(requests[0].url.params)['transactionType'] == '0'
    assert requests[0].url.params['page'] == '2'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [202, 301, 302, 400, 401, 403, 404, 429, 500])
async def test_melo_refusal_and_unexpected_status_never_succeed_or_leak_key(monkeypatch, status):
    requests = transport(monkeypatch, {'hydra:description': 'Rejected ' + TOKEN}, status)
    result = await node({'operation': 'list_searches'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'hydra:member': None}, {'hydra:member': [1]}, {'error': 'bad'}, {'hydra:description': 'bad'}])
async def test_melo_malformed_or_error_collections_are_not_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'list_searches'}).execute({})


@pytest.mark.asyncio
async def test_melo_documented_search_collection(monkeypatch):
    fixture = json.loads((Path(__file__).parent / 'fixtures/melo/searches.json').read_text())
    transport(monkeypatch, fixture)
    result = await node({'operation': 'list_searches'}).execute({})
    assert result['items'] == fixture['hydra:member']


def test_melo_manual_credential_and_schema():
    assert native.MeloAPIKeyCredential(api_key=TOKEN).credential_type == 'melo_api_key'
    assert native.MeloNode.connection_evidence.operation == 'list_searches'
    assert {key: list(value) for key, value in native.ROUTES.items()} == CONTRACT_ROUTES
    for key in ['https://stream.estate/console', '<token>', 'key with spaces']:
        with pytest.raises(ValueError):
            native.MeloAPIKeyCredential(api_key=key)
    for config in [
        {'operation': 'get_search', 'id': '../outside'},
        {'operation': 'create_search', 'title': 'Missing types'},
        {'operation': 'list_properties', 'itemsPerPage': 31},
        {'operation': 'list_points_of_interest', 'facilities': ['school'], 'lat': 91, 'lon': 2, 'radius': 1},
    ]:
        with pytest.raises((ValueError, ValidationError)):
            node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', [op for op in CONTRACT_ROUTES if op != 'delete_search'])
async def test_melo_parses_whole_provider_documented_responses(monkeypatch, operation):
    method, path = CONTRACT_ROUTES[operation]
    config = {'operation': operation}
    if '{id}' in path:
        config['id'] = ID
    if method in {'POST', 'PUT'}:
        config.update(title='mySearch', propertyTypes=[0, 1], transactionType=0)
    if operation == 'list_points_of_interest':
        config.update(facilities=['school'], lat=48.8803424, lon=2.333215, radius=0.5)
    body = DOCUMENTED[method + ' ' + path]['body']
    transport(monkeypatch, body, 201 if method == 'POST' else 200)
    result = await node(config).execute({})
    assert result['status'] == 'success' and result['data'] == body
