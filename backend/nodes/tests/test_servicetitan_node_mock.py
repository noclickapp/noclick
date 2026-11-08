"""Exercise ServiceTitan's real factory and transport boundary without an account."""
import json
import httpx
import pytest
from nodes import servicetitan_node as native
from nodes.core.registry import NodeFactory, NODE_REGISTRY

CREDS = {'credential_type': 'servicetitan_token', 'access_token': 'synthetic-access-44',
         'app_key': 'synthetic-app-55', 'tenant_id': '12345'}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config, **credentials):
    return NodeFactory.create_node(node_id='fixture', node_type='automation-servicetitan',
        node_data={'config': config, 'credentials': {**CREDS, **credentials}})

def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', native.OPERATIONS)
async def test_exact_contract_routes_bodies_auth_and_pagination(monkeypatch, operation):
    method, path, kind = native.OPERATIONS[operation]
    config = {'operation': operation}
    if '{id}' in path: config['id'] = 77
    if kind == 'update': config['summary' if operation.endswith('lead') else 'name'] = 'Updated'
    if kind == 'note': config.update(text='Please call tomorrow', pin_to_top=True)
    if kind == 'followup': config['follow_up_date'] = '2026-11-09T10:00:00Z'
    if kind == 'dismiss': config['dismissing_reason_id'] = 99
    body = {'page': 1, 'data': [{'id': 77, 'name': 'Account customer'}], 'hasMore': True, 'totalCount': 51} if kind == 'list' else {'id': 77}
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    request, = requests
    assert request.method == method
    assert request.url.path == '/crm' + path.format(tenant='12345', id=77)
    assert request.headers['Authorization'] == 'Bearer ' + CREDS['access_token']
    assert request.headers['ST-App-Key'] == CREDS['app_key']
    if kind == 'list':
        assert dict(request.url.params) == {'page': '1', 'pageSize': '50', 'includeTotal': 'true'}
        assert result['next_page'] == 2
    elif kind == 'note': assert json.loads(request.content) == {'text': config['text'], 'pinToTop': True}
    elif kind == 'dismiss': assert json.loads(request.content) == {'dismissingReasonId': 99}
    elif kind == 'update': assert json.loads(request.content) == {k:v for k,v in config.items() if k not in {'id','operation'}}
    elif kind == 'followup': assert json.loads(request.content) == {'followUpDate': '2026-11-09T10:00:00+00:00'}

@pytest.mark.asyncio
async def test_environment_empty_last_page_and_error_redaction(monkeypatch):
    requests = transport(monkeypatch, {'page': 2, 'data': [], 'hasMore': False})
    result = await node({'operation': 'list_customers', 'page': 2}, environment='integration').execute({})
    assert requests[0].url.host == 'api-integration.servicetitan.io'
    assert result['next_page'] is None and result['data'] == []
    transport(monkeypatch, {'error': CREDS['access_token'] + CREDS['app_key']}, 401)
    result = await node({'operation': 'list_customers'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == 401
    assert not any(secret in str(result) for secret in (CREDS['access_token'], CREDS['app_key']))

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'page': 1, 'data': {}, 'hasMore': False}, {'page': 9, 'data': [], 'hasMore': False}])
async def test_malformed_or_mismatched_page_fails(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({'operation': 'list_customers'}).execute({}))['status'] == 'error'

@pytest.mark.parametrize('change', [{'tenant_id': '../other'}, {'environment': 'https://evil.test'}, {'access_token': 'Bearer x'}])
def test_credential_boundaries(change):
    with pytest.raises(ValueError): native.ServiceTitanTokenCredential(**{**CREDS, **change})

def test_registration():
    assert NODE_REGISTRY['automation-servicetitan'] is native.ServiceTitanNode

def test_follow_up_requires_timezone():
    with pytest.raises(ValueError):
        native.CreateLeadFollowUpConfig(id=1, follow_up_date='2026-11-09T10:00:00')
