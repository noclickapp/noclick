"""Holded factory, request routing, pagination, writes and credential failures."""
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import holded_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-holded-secret'
ID = '507f1f77bcf86cd799439011'

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

def node(config):
    return NodeFactory.create_node(node_id='holded-fixture', node_type='automation-holded',
        node_data={'config': config, 'credentials': {'credential_type': 'holded_api_key', 'api_key': TOKEN}})

def wire(monkeypatch, status=200, body=None):
    requests=[]
    def respond(req):
        requests.append(req)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(status)
    def client(**kw):
        assert kw['follow_redirects'] is False and kw['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kw)
    monkeypatch.setattr(native,'guarded_async_client',client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('resource,singular,ident', [('contacts','contact','contactId'),('invoices','invoice','invoiceId'),('products','product','productId'),('projects','project','projectId'),('tasks','task','taskId')])
@pytest.mark.parametrize('action,method',[('list','GET'),('get','GET'),('create','POST'),('update','PUT'),('delete','DELETE')])
async def test_all_operations_one_contract_request(monkeypatch,resource,singular,ident,action,method):
    config={'operation':action+'_'+(resource if action=='list' else singular)}
    if action in {'get','update','delete'}:config[ident]=ID
    if action in {'create','update'}:
        if singular=='invoice':config.update(contact_id=ID,items=[{'name':'Consulting','units':1,'price':125}])
        else:config['name']='Example customer'
        if singular=='product' and action=='create':config.update(kind='simple',has_stock=False,for_sale=True,for_purchase=False)
        if singular=='product' and action=='update':config.update(archived=False,for_sale=True,for_purchase=False)
        if singular=='task':config['project_id']=ID
    if action=='list':config.update(limit=25,cursor='opaque-next')
    body={'items':[{'id':ID,'name':'Example'}],'has_more':True,'cursor':'next'} if action=='list' else {'id':ID}
    requests=wire(monkeypatch,204 if action=='delete' else 201 if action=='create' else 200,body)
    result=await node(config).execute({})
    assert len(requests)==1
    req=requests[0]
    assert req.method==method and req.url.host=='api.holded.com'
    assert req.url.path=='/api/v2/'+resource+('/'+ID if action in {'get','update','delete'} else '')
    assert req.headers['authorization']=='Bearer '+TOKEN
    if action=='list':
        assert dict(req.url.params)=={'limit':'25','cursor':'opaque-next'}
        assert result==body
    if action in {'create','update'}:
        sent=json.loads(req.content)
        assert 'operation' not in sent and ident not in sent
        assert sent=={k:v for k,v in config.items() if k not in {'operation',ident}}
    if action=='delete':assert result=={'status':'success','deleted':True}

@pytest.mark.asyncio
@pytest.mark.parametrize('status',[400,401,403,429,500])
async def test_provider_rejection_keeps_message_and_redacts_secret(monkeypatch,status):
    requests=wire(monkeypatch,status,{'detail':'Rejected '+TOKEN})
    with pytest.raises(ValueError,match='Rejected') as exc:await node({'operation':'list_contacts'}).execute({})
    assert TOKEN not in str(exc.value) and len(requests)==1

@pytest.mark.asyncio
async def test_evidence_read_and_empty_accounts(monkeypatch):
    wire(monkeypatch,body={'items':[],'cursor':None,'has_more':False})
    assert native.HoldedNode.connection_evidence.operation=='list_contacts'
    assert (await node({'operation':'list_contacts'}).execute({}))['items']==[]

@pytest.mark.parametrize('value',['https://holded.com/key','<token>','Bearer abc','a\nb'])
def test_reject_bad_credentials(value):
    with pytest.raises(ValidationError):native.HoldedAPIKey(api_key=value)

@pytest.mark.asyncio
async def test_nested_invoice_and_date_serialization(monkeypatch):
    requests=wire(monkeypatch,201,{'id':ID})
    await node({'operation':'create_invoice','contact_id':ID,'date':'2026-11-08','items':[{'name':'Service','units':2,'price':12.5}]}).execute({})
    assert json.loads(requests[0].content)['date']=='2026-11-08'

@pytest.mark.asyncio
async def test_success_secret_echo_is_redacted(monkeypatch):
    wire(monkeypatch,body={'id':ID,'name':TOKEN,'api_key':TOKEN})
    assert TOKEN not in str(await node({'operation':'get_contact','contactId':ID}).execute({}))

@pytest.mark.asyncio
async def test_explicit_null_clears_a_field_while_unset_fields_stay_absent(monkeypatch):
    requests=wire(monkeypatch,body={'id':ID})
    await node({'operation':'update_project','projectId':ID,'description':None}).execute({})
    assert json.loads(requests[0].content)=={'description':None}
