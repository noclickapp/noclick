"""Native Common Room request and schema-based poll replay tests; no live credentials."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import common_room_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures/common-room'
CASES = json.loads((FIXTURES / 'requests.json').read_text())
ACTIVITY = json.loads((FIXTURES / 'activity.json').read_text())['body']
TOKEN = 'synthetic-common-room-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='common-room-test', node_type='automation-common-room',
        node_data={'config':config,'credentials':{'credential_type':'common_room_api_token','api_token':TOKEN}})

def transport(monkeypatch, replies):
    seen=[]
    def respond(request):
        seen.append(request)
        return replies.pop(0)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond),**kwargs)
    monkeypatch.setattr(native,'guarded_async_client',client)
    return seen

@pytest.mark.asyncio
@pytest.mark.parametrize('case',CASES,ids=lambda c:c['config']['operation'])
async def test_common_room_contract_requests(monkeypatch,case):
    reply={'success':True,'data':{'id':'s_123'}}
    seen=transport(monkeypatch,[httpx.Response(200,json=reply)])
    assert await node(case['config']).execute({}) == reply
    assert len(seen)==1
    req=seen[0]
    assert req.url.host=='api.commonroom.io'
    assert req.method==case['method'] and req.url.path==case['path']
    assert req.headers['authorization']=='Bearer '+TOKEN
    assert dict(req.url.params)==case['params']
    assert (json.loads(req.content) if req.content else None)==case['body']

@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload',[(403,{'message':'Token rejected'}),(429,{'message':'Rate limited'}),(200,{'success':False})])
async def test_common_room_rejections(monkeypatch,status,payload):
    transport(monkeypatch,[httpx.Response(status,json=payload)])
    with pytest.raises(ValueError): await node({'operation':'get_me'}).execute({})

@pytest.mark.parametrize('config',[
    {'operation':'get_contact','id':'../me'},
    {'operation':'list_activities','startDate':'2026-11-10T12:00:00'},
    {'operation':'update_contacts','contactIds':['c_123']},
    {'operation':'update_contacts','contactIds':[],'segmentId':'s_123'},
    {'operation':'create_segment','name':'Objects','entityType':'object'},
])
def test_common_room_invalid_config(config):
    with pytest.raises(ValueError):node(config)

@pytest.mark.asyncio
async def test_common_room_activity_poll_baseline_and_dedup(monkeypatch):
    seen=transport(monkeypatch,[httpx.Response(200,json=ACTIVITY) for _ in range(3)])
    n=node({'operation':'on_new_activity','contactId':'c_123'})
    state={}
    async def update(mutator,skip_result=None):
        nonlocal state
        updated,result=mutator(state)
        if updated is not None:state=updated
        return result
    monkeypatch.setattr(n,'_update_node_state',update)
    assert (await n.execute({}))['activities']==[]
    state['seen_ids']=[]
    output=await n.execute({})
    assert output['activities']==ACTIVITY['data']
    event=n.resolve_agent_event(output)
    assert all(value in event['text'] for value in ['c_123','a_123','Interested in a demo','X'])
    assert (await n.execute({}))['activities']==[]
    assert seen[0].url.params['sort']=='activityTime'
    assert seen[0].url.params['contactId']=='c_123'
    assert n.trigger_produced_no_event({})

@pytest.mark.asyncio
async def test_common_room_pagination_and_cycle(monkeypatch):
    first={**ACTIVITY,'meta':{'nextCursor':'next'}}
    transport(monkeypatch,[httpx.Response(200,json=first),httpx.Response(200,json=first)])
    with pytest.raises(ValueError,match='nonadvancing'):
        await node({'operation':'on_new_activity'}).execute({})

@pytest.mark.asyncio
async def test_common_room_list_preserves_cursor(monkeypatch):
    payload={'success':True,'data':[],'meta':{'nextCursor':'next-page'}}
    seen=transport(monkeypatch,[httpx.Response(200,json=payload)])
    assert await node({'operation':'list_contacts','cursor':'previous'}).execute({})==payload
    assert seen[0].url.params['cursor']=='previous'

@pytest.mark.asyncio
async def test_common_room_typed_custom_field_write(monkeypatch):
    seen=transport(monkeypatch,[httpx.Response(200,json={"success":True,"data":{}})])
    fields=[{"customFieldId":"cf_123","customFieldValue":{"type":"boolean","value":True}}]
    await node({"operation":"update_contacts","contactIds":["c_123"],"customFields":fields}).execute({})
    assert json.loads(seen[0].content)["customFields"]==fields

@pytest.mark.parametrize("value",["1",{"type":"int","value":"42"},{"type":"boolean","value":"true"}])
def test_common_room_rejects_untyped_custom_values(value):
    with pytest.raises(ValueError):
        node({"operation":"update_contacts","contactIds":["c_123"],"customFields":[{"customFieldId":"cf_123","customFieldValue":value}]})
