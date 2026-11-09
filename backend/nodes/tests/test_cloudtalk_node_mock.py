"""Offline HTTP-boundary coverage; no real credentials or provider actions."""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import cloudtalk_node as native
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {'credential_type':'cloudtalk_api_key','access_key_id':'synthetic-access-id','access_key_secret':'synthetic-access-secret'}
FIXTURES = json.loads((Path(__file__).parent / 'fixtures/cloudtalk/responses.json').read_text())
CONFIGS = {
 'list_contacts':{'search':'acme'},
 'create_contact':{'name':'Sam Rivera','type':'lead','company':'Northwind','countryCode':'GB','phones':['+447700900123'],'emails':['sam.rivera@example.com'],'tagIds':['131'],'matchBy':'emailOrPhone','idempotency_key':'fixture-1'},
 'get_contact':{'contact_id':'44210'},
 'update_contact':{'contact_id':'44210','title':'VP Procurement','clear_fields':['website'],'customFields':{'Segment':'mid-market','Legacy ID':None}},
 'delete_contact':{'contact_id':'44210'},
 'add_contact_tags':{'contact_id':'44210','tagIds':['123','131']},
 'remove_contact_tags':{'contact_id':'44210','tagIds':['123','131']},
 'list_contact_tags':{},'create_contact_tag':{'name':'renewal-q1'},
 'rename_contact_tag':{'tag_id':'152','name':'renewal-2027-q1'},'delete_contact_tag':{'tag_id':'152'},
 'list_contact_fields':{},'list_agents':{'limit':3,'associated_number':'+421123456789'},
 'list_groups':{},'list_numbers':{'is_free':0},'list_notes':{'contact_id':567},
 'add_note':{'contact_id':567,'note':'Note content...','user_id':456},
 'list_calls':{'contact_id':1234,'type':'outgoing','status':'answered','date_from':'2026-11-01T00:00:00Z'},
 'get_call':{'call_id':12345},
 'send_sms':{'recipient':'+421123456789','sender':'+421987654321','message':'Test message'},
 'make_call':{'agent_id':1234,'callee_number':'+442012345678'},
}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        assert request.url.host in {'api.cloudtalk.io','my.cloudtalk.io','analytics-api.cloudtalk.io'}
        assert request.headers['authorization'] == 'Basic ' + base64.b64encode((AUTH['access_key_id']+':'+AUTH['access_key_secret']).encode()).decode()
        assert AUTH['access_key_secret'] not in str(request.url)
        code, body = responses.pop(0)
        return httpx.Response(code,json=body) if code != 204 else httpx.Response(204)
    original = ssrf.guarded_async_client
    monkeypatch.setattr(native,'guarded_async_client',lambda **kw: original(**kw,transport=httpx.MockTransport(send)))
    return requests,responses

def node(operation, **changes):
    return NodeFactory.create_node(node_id='cloudtalk-test',node_type='automation-cloudtalk',
        node_data={'config':{'operation':operation,**CONFIGS[operation],**changes},'credentials':AUTH})

@pytest.mark.asyncio
@pytest.mark.parametrize('operation',CONFIGS)
async def test_cloudtalk_each_operation_matches_published_route(transport,operation):
    requests,responses=transport
    fixture=FIXTURES[operation]
    responses.append((fixture['status'],fixture['body']))
    result=await node(operation).execute({})
    assert result['status']=='success' and len(requests)==1
    request=requests[0]
    path=fixture['path'].replace('{contactId}',str(CONFIGS[operation].get('contact_id',''))).replace('{tagId}',str(CONFIGS[operation].get('tag_id',''))).replace('{callId}',str(CONFIGS[operation].get('call_id','')))
    prefix='/v1' if operation in list(CONFIGS)[:12] else '/api'
    assert request.url.path==prefix+path and request.method==fixture['method']
    assert request.headers['accept']=='application/json'
    if operation=='get_call':assert request.url.host=='analytics-api.cloudtalk.io'
    if operation=='create_contact':
        assert request.headers['idempotency-key']=='fixture-1'
        assert json.loads(request.content)=={k:v for k,v in CONFIGS[operation].items() if k!='idempotency_key'}
    if operation=='update_contact':assert json.loads(request.content)=={'title':'VP Procurement','website':None,'customFields':{'Segment':'mid-market','Legacy ID':None}}
    if operation=='remove_contact_tags':assert request.url.params['tagIds']=='123,131' and not request.content
    if operation=='add_contact_tags':assert json.loads(request.content)=={'tagIds':['123','131']}
    if operation=='list_numbers':assert request.url.params['is_free']=='0'
    if operation in {'send_sms','make_call'}:assert result['request_acknowledged'] is True and result['delivery_verified'] is False
    if operation=='list_agents':assert result['data'][0]['email']=='joh.doe@phoonio.com'

@pytest.mark.asyncio
async def test_cloudtalk_cursor_and_page_pagination(transport):
    requests,responses=transport
    body=FIXTURES['list_contacts']['body'];responses.append((200,body))
    result=await node('list_contacts',cursor='opaque/+==').execute({})
    assert requests[0].url.params['cursor']=='opaque/+=='
    assert result['next_cursor']==body['pagination']['next']
    responses.append((200,{'responseData':{'data':[],'pageNumber':2,'pageCount':3,'itemsCount':201,'limit':100}}))
    assert (await node('list_agents',page=2).execute({}))['next_page']==3

@pytest.mark.asyncio
@pytest.mark.parametrize('code,body',[
 (401,{'responseData':{'status':401,'message':'Unauthorized action'}}),
 (429,{'responseData':{'status':429,'message':'Too many requests'}}),
 (200,{'responseData':{'success':False,'data':'SMS send failed'}}),
 (200,{'responseData':{'success':'false','data':'SMS send failed'}}),
 (200,{'responseData':{'status':406,'message':'Invalid input data'}}), (302,{})])
async def test_cloudtalk_errors_never_succeed_or_retry(transport,code,body):
    requests,responses=transport;responses.append((code,body))
    with pytest.raises(ValueError):await node('send_sms').execute({})
    assert len(requests)==1

@pytest.mark.asyncio
async def test_cloudtalk_redacts_errors_and_rejects_malformed_evidence(transport):
    _,responses=transport;responses.append((401,{'responseData':{'message':AUTH['access_key_secret']}}))
    with pytest.raises(ValueError) as exc:await node('list_agents').execute({})
    assert AUTH['access_key_secret'] not in str(exc.value)
    responses.append((200,{'responseData':{'data':'invalid'}}))
    with pytest.raises(ValueError,match='list envelope'):await node('list_agents').execute({})

@pytest.mark.parametrize('operation,changes',[
 ('get_contact',{'contact_id':'../../other'}),('get_contact',{'contact_id':'x?admin=true'}),
 ('update_contact',{'title':None,'clear_fields':[],'customFields':None}),
 ('update_contact',{'clear_fields':['title']}),('list_contacts',{'customField':'CRM ID'}),
 ('create_contact',{'matchBy':'email','emails':[]}),('send_sms',{'recipient':'invalid'})])
def test_cloudtalk_invalid_config_is_rejected(operation,changes):
    with pytest.raises(ValueError):node(operation,**changes)

def test_cloudtalk_manual_credential_and_evidence():
    shaped=native.CloudTalkAPIKeyCredential(access_key_id=' synthetic-access-id ',access_key_secret='synthetic-access-secret')
    assert shaped.credential_type=='cloudtalk_api_key' and shaped.access_key_id=='synthetic-access-id'
    for bad in ['https://example.com/token','Basic abc:def','bad\r\nheader']:
        with pytest.raises(ValidationError):native.CloudTalkAPIKeyCredential(access_key_id=bad,access_key_secret='synthetic-access-secret')
    assert native.CloudTalkNode.connection_evidence.operation=='list_agents'
    assert set(CONFIGS)==set(native.OPERATIONS)
