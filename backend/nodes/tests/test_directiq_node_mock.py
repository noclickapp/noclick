"""Offline HTTP-boundary tests against DirectIQ's published operation schemas."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import jsonschema
import pytest
from pydantic import TypeAdapter, ValidationError
from nodes import directiq_node as api
from nodes.core.registry import NodeFactory

HERE = Path(__file__).parent / 'fixtures/directiq'
CONFIGS = json.loads((HERE / 'configs.json').read_text())
CONTRACT = json.loads((HERE / 'contract.json').read_text())
TOKEN = 'synthetic-directiq-key'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    n = NodeFactory.create_node(node_id='directiq-test', node_type='automation-directiq', node_data={
        'config':config, 'credentials':{'credential_type':'directiq_api_key','api_key':TOKEN}})
    n.emit = AsyncMock()
    return n

def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert not kwargs['follow_redirects'] and not kwargs['trust_env']
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr(api, 'guarded_async_client', client)

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CONFIGS)
async def test_published_requests(monkeypatch, operation):
    expected = CONTRACT['operations'][operation]
    seen = []
    def handler(request):
        seen.append(request)
        assert request.method == expected['method']
        assert request.url.host == 'api.directiq.com'
        assert request.url.path == expected['path'].replace('{id}','42').replace('{note_id}','42')
        assert request.headers['x-api-key'] == TOKEN
        assert 'authorization' not in request.headers
        assert set(request.url.params) <= {p['name'] for p in expected['parameters'] if p['in']=='query'}
        if expected['request_body']:
            schemas = CONTRACT['schemas']['core' if '/core/' in expected['source'] else 'contacts']
            jsonschema.Draft4Validator({'components':{'schemas':schemas}, **expected['request_body']}).validate(json.loads(request.content))
        else:
            assert not request.content
        status = int(next(k for k in expected['responses'] if k.startswith('2')))
        if status in (202,204):return httpx.Response(status)
        return httpx.Response(status,json={'data':[],'has_more':False,'next_page_token':None,'id':42})
    transport(monkeypatch,handler)
    result = await node(CONFIGS[operation]).execute({})
    assert result['status']=='success' and len(seen)==1
    if operation=='delete_list':assert result['acknowledged'] and not result['completed']

@pytest.mark.asyncio
async def test_pagination(monkeypatch):
    payload={'data':[{'id':42,'name':'Newsletter'}],'has_more':True,'next_page_token':'next+/='}
    def handler(request):
        assert dict(request.url.params)=={'limit':'2','page_token':'previous+/='}
        return httpx.Response(200,json=payload)
    transport(monkeypatch,handler)
    assert (await node({'operation':'list_lists','limit':2,'page_token':'previous+/='}).execute({}))['data']==payload

@pytest.mark.asyncio
@pytest.mark.parametrize('status',[302,400,401,403,404,409,422,429,500])
async def test_errors_preserve_provider_message_redact_key(monkeypatch,status):
    transport(monkeypatch,lambda r:httpx.Response(status,json={'title':'Unauthorized','detail':'Rejected '+TOKEN}))
    result=await node(CONFIGS['list_lists']).execute({})
    assert result['status']=='error' and result['http_status']==status
    assert TOKEN not in json.dumps(result) and 'Rejected' in result['message']

@pytest.mark.asyncio
@pytest.mark.parametrize('content',[b'not-json',b'[]',b'{}',b'{"data":{},"has_more":false}'])
async def test_invalid_page(monkeypatch,content):
    transport(monkeypatch,lambda r:httpx.Response(200,content=content))
    with pytest.raises(ValueError):await node(CONFIGS['list_lists']).execute({})

@pytest.mark.parametrize('config',[
    {'operation':'get_list','id':'../other'},{'operation':'get_list','id':0},
    {'operation':'list_contacts','limit':101},{'operation':'list_contacts','status':'invented'},
    {'operation':'create_list','name':''},{'operation':'add_contact_note','id':42,'note':'x'*501},
    {'operation':'import_contacts','id':42,'email':''},
    {'operation':'import_contacts','id':42},
])
def test_invalid_input(config):
    with pytest.raises((ValueError,ValidationError)):TypeAdapter(api.Operation).validate_python(config)

def test_manual_credential_default():
    assert api.DirectIQAPIKeyCredential(api_key=TOKEN).credential_type=='directiq_api_key'
