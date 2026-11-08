"""Execute real TimelinesAI nodes against captured HTTP transports."""
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import timelinesai_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id="timelinesai-test", node_type="automation-timelinesai",
        node_data={"config":config,"credentials":{"credential_type":"timelinesai_api_token","api_token":"synthetic-api-token"}})

@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,query,body',[
    ({'operation':'list_chats','page':2,'closed':False},'GET','/chats',{'page':'2','closed':'false'},None),
    ({'operation':'send_chat_message','chat_id':1000001,'text':'hello, world!','reply_to':'message-uid'},'POST','/chats/1000001/messages',{}, {'text':'hello, world!','reply_to':'message-uid'}),
    ({'operation':'update_chat','chat_id':1000001,'read':False,'unassign_responsible':True},'PATCH','/chats/1000001',{}, {'read':False,'responsible':''}),
    ({'operation':'replace_chat_labels','chat_id':1000001,'labels':[]},'POST','/chats/1000001/labels',{}, {'labels':[]}),
    ({'operation':'add_chat_note','chat_id':1000001,'text':'Follow up'},'POST','/chats/1000001/notes',{}, {'text':'Follow up','is_private':True}),
    ({'operation':'send_message_to_phone','phone':'+14840000000','text':'hello'},'POST','/messages',{}, {'phone':'+14840000000','text':'hello'}),
    ({'operation':'create_template','name':'Greeting','text':'Hello'},'POST','/templates',{}, {'name':'Greeting','text':'Hello','visibility':'public'}),
    ({'operation':'delete_file','file_uid':'file-uid'},'DELETE','/files/file-uid',{},None),
    ({'operation':'get_current_teammate'},'GET','/workspace/teammates/me',{},None),
])
async def test_request_contract(monkeypatch,config,method,path,query,body):
    requests=[]
    response={'status':'ok','data':{'name':'Account','unknown_future_field':True}}
    def handle(request):
        requests.append(request)
        return httpx.Response(200,json=response)
    monkeypatch.setattr(native,'guarded_async_client',lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(handle),**kw))
    assert await node(config).execute({}) == response
    assert len(requests)==1
    request=requests[0]
    assert request.method==method
    assert request.url.host=='app.timelines.ai'
    assert request.url.path=='/integrations/api'+path
    assert dict(request.url.params)==query
    assert request.headers['authorization']=='Bearer synthetic-api-token'
    assert (json.loads(request.content) if request.content else None)==body

@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload',[(401,{'message':'Token rejected'}),(200,{'status':'error','message':'Token rejected'})])
async def test_rejection_preserves_provider_message(monkeypatch,status,payload):
    monkeypatch.setattr(native,'guarded_async_client',lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(status,json=payload)),**kw))
    with pytest.raises(ValueError,match='Token rejected'):
        await node({'operation':'get_current_teammate'}).execute({})

@pytest.mark.parametrize('config',[
    {'operation':'send_chat_message','chat_id':1},
    {'operation':'get_chat','chat_id':0},
    {'operation':'create_template','name':'','text':'Hello'},
    {'operation':'add_chat_note','chat_id':1,'text':'bad\0note'},
])
def test_invalid_config(config):
    with pytest.raises(ValueError): node(config)

@pytest.mark.asyncio
async def test_empty_delete_acknowledgement(monkeypatch):
    monkeypatch.setattr(native,'guarded_async_client',lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200)),**kw))
    assert await node({'operation':'delete_file','file_uid':'file-uid'}).execute({}) == {'status':'ok','deleted_file_uid':'file-uid'}
