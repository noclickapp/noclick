"""Exercise the native factory and HTTP boundary without a provider account."""
import json
import httpx
import pytest
from nodes import openrouter_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

TOKEN = 'openrouter-synthetic-key-42'
def node(config):
    return NodeFactory.create_node(node_id='router', node_type='automation-openrouter', node_data={
        'config': config, 'credentials': {'credential_type':'openrouter_api_key','api_key':TOKEN}})

def transport(monkeypatch, body, status=200):
    calls=[]
    original=httpx.AsyncClient
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    return calls

@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', [
    ({'operation':'get_current_key'},'GET','/key',{'data':{'label':'Production','limit':20}}),
    ({'operation':'get_generation','id':'gen-123'},'GET','/generation',{'data':{'id':'gen-123'}}),
    ({'operation':'list_model_endpoints','author':'openai','slug':'gpt-4'},'GET','/models/openai/gpt-4/endpoints',{'data':{'endpoints':[]}}),
    ({'operation':'create_chat_completion','model':'openai/gpt-4','messages':[{'role':'user','content':'Hello!'}]},'POST','/chat/completions',{'choices':[{'message':{'role':'assistant','content':'Hello'}}]}),
    ({'operation':'create_embeddings','model':'openai/text-embedding-3-small','input':'Hello'},'POST','/embeddings',{'data':[{'embedding':[0.1]}]}),
    ({'operation':'create_key','name':'Workflow','limit':5},'POST','/keys',{'key':'new-key','data':{'name':'Workflow'}}),
    ({'operation':'update_key','hash':'abc','limit':None,'disabled':False},'PATCH','/keys/abc',{'data':{'limit':None}}),
    ({'operation':'delete_key','hash':'abc'},'DELETE','/keys/abc',{'deleted':True}),
])
async def test_requests_and_response(monkeypatch,config,method,path,body):
    calls=transport(monkeypatch,body)
    result=await node(config).execute({})
    assert result == {'status':'success',**body}
    assert len(calls)==1
    request=calls[0]
    assert request.method==method and request.url.path=='/api/v1'+path
    assert request.headers['authorization']=='Bearer '+TOKEN
    if config['operation']=='get_generation': assert request.url.params['id']=='gen-123'
    if method in {'POST','PATCH'}:
        payload=json.loads(request.content)
        if config['operation']=='update_key': assert payload=={'limit':None,'disabled':False}
        if config['operation']=='create_chat_completion': assert payload['stream'] is False
        if config['operation']=='create_embeddings': assert payload['encoding_format']=='float'

@pytest.mark.asyncio
async def test_rejection_preserves_provider_message_and_status(monkeypatch):
    transport(monkeypatch,{'error':{'message':'Invalid API key: '+TOKEN}},401)
    result=await node({'operation':'get_current_key'}).execute({})
    assert result=={'status':'error','http_status':401,'error':'Invalid API key: [redacted]'}

@pytest.mark.parametrize('field', ['author','slug'])
def test_path_injection_rejected(field):
    with pytest.raises(ValueError):
        node({'operation':'list_model_endpoints','author':'openai','slug':'gpt-4',field:'../keys'})

@pytest.mark.asyncio
async def test_model_page_size_maps_to_limit_without_changing_key_limits(monkeypatch):
    calls=transport(monkeypatch,{'data':[]})
    await node({'operation':'list_models','page_size':25,'offset':50}).execute({})
    assert dict(calls[0].url.params)=={'limit':'25','offset':'50'}

@pytest.mark.asyncio
async def test_update_preserves_omission_and_explicit_null(monkeypatch):
    calls=transport(monkeypatch,{'data':{'label':'Workflow'}})
    await node({'operation':'update_key','hash':'abc','name':'Workflow'}).execute({})
    assert json.loads(calls[0].content)=={'name':'Workflow'}
    await node({'operation':'update_key','hash':'abc','limit':None,'limit_reset':None}).execute({})
    assert json.loads(calls[1].content)=={'limit':None,'limit_reset':None}
