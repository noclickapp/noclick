"""MineSkin wire-contract regressions; no live key or generation used."""
import json
from pathlib import Path
from uuid import UUID
import httpx
import pytest
from pydantic import ValidationError
from nodes import mineskin_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-mineskin-key-123'
FIXTURES = Path(__file__).parent / 'fixtures' / 'mineskin'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='mineskin-test', node_type='automation-mineskin', node_data={
        'config': config, 'credentials': {'credential_type': 'mineskin_api_key', 'api_key': TOKEN}})


def wire(monkeypatch, body, status=200):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,path', [(op, route) for op, (method, route) in native.ROUTES.items() if method == 'GET'])
async def test_read_routes_and_bearer(monkeypatch, operation, path):
    config = {'operation': operation}
    if operation == 'get_job':
        config['job_id'] = 'job-123'
    if operation == 'get_skin':
        config['uuid'] = 'c891dfac4cd247a2a55743e7e82ce76f'
    if operation == 'list_skins':
        config['after'] = 'previous-skin'
    body = json.loads((FIXTURES / 'account.json').read_text()) if operation == 'get_user' else {'jobs': [], 'capes': [], 'skins': []}
    requests = wire(monkeypatch, body)
    result = await node(config).execute({})
    assert result['status'] == 'success' and result['data'] == body
    request = requests[0]
    assert len(requests) == 1 and request.method == 'GET'
    assert request.url.path == path.format(job_id=config.get('job_id'), uuid=str(UUID(config['uuid'])) if 'uuid' in config else None)
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.headers['User-Agent'].startswith('NoClick/')
    assert dict(request.url.params) == ({'after': 'previous-skin'} if operation == 'list_skins' else {})
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,path', [('generate_skin','/v2/generate'), ('queue_skin','/v2/queue'), ('queue_batch','/v2/queue/batch')])
async def test_generation_documented_example_exact_json(monkeypatch, operation, path):
    fixture = json.loads((FIXTURES / 'requests.json').read_text())
    body = fixture['batch'] if operation == 'queue_batch' else fixture['url']
    requests = wire(monkeypatch, {'success': True, 'job': {'id': 'test-job', 'status': 'waiting'}}, 202)
    result = await node({'operation': operation, **body}).execute({})
    assert result['http_status'] == 202 and result['data']['job']['status'] == 'waiting'
    assert len(requests) == 1 and requests[0].url.path == path
    assert json.loads(requests[0].content) == body


@pytest.mark.asyncio
async def test_player_generation_and_options(monkeypatch):
    body = {'user': '61699b2ed3274a019f1e0ea8c3f06bc6', 'name': 'My Example Skin', 'variant': 'classic', 'visibility': 'private'}
    requests = wire(monkeypatch, {'success': True})
    await node({'operation': 'queue_skin', **body}).execute({})
    assert json.loads(requests[0].content) == body


@pytest.mark.parametrize('config', [
    {'operation':'queue_skin'},
    {'operation':'generate_skin','url':'https://i.imgur.com/kQPrtYw.png','user':'61699b2ed3274a019f1e0ea8c3f06bc6'},
    {'operation':'queue_batch','batch':[]},
    {'operation':'queue_batch','batch':[{'url':'https://i.imgur.com/kQPrtYw.png'}]*25},
    {'operation':'get_job','job_id':'../me'},
    {'operation':'get_skin','uuid':'not-a-uuid'},
    {'operation':'list_jobs','since':123},
])
def test_invalid_inputs_refused(config):
    assert not native.MineSkinNode.validate_config({'config':config,'credentials':{'api_key':TOKEN}})['valid']


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'success':False,'errors':[{'message':'Invalid API key'}]}), (429,{'success':False,'errors':[{'message':'Rate limit'}]}), (200,{'success':False,'errors':[{'message':'Denied'}]})])
async def test_errors_are_not_connection_success(monkeypatch, status, body):
    wire(monkeypatch, body, status)
    result = await node({'operation':'get_user'}).execute({})
    assert result['status'] == 'error' and result['error'] == body['errors']


@pytest.mark.asyncio
async def test_malformed_identity_is_unverified(monkeypatch):
    wire(monkeypatch, {'success':True})
    with pytest.raises(ValueError, match='current user'):
        await node({'operation':'get_user'}).execute({})


@pytest.mark.asyncio
async def test_response_redacts_key_and_preserves_partial_batch(monkeypatch):
    wire(monkeypatch, {'success':True, 'batch':[{'success':False,'errors':[{'message':TOKEN}]}]}, 202)
    result = await node({'operation':'queue_batch','batch':[{'url':'https://i.imgur.com/kQPrtYw.png'}]}).execute({})
    assert result['data']['batch'][0]['success'] is False
    assert TOKEN not in str(result)


def test_manual_credential_default_and_secret_validation():
    assert native.MineSkinAPIKeyCredential(api_key=TOKEN).credential_type == 'mineskin_api_key'
    for invalid in ['Bearer x', 'https://account.mineskin.org/keys', '<token>']:
        with pytest.raises(ValidationError):
            native.MineSkinAPIKeyCredential(api_key=invalid)
