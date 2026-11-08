"""Transport regressions for Manyreach's published v2 contract."""
import json
import httpx
import pytest
from nodes import manyreach_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='manyreach-test', node_type='automation-manyreach', node_data={
        'config':config, 'credentials':{'credential_type':'manyreach_api_key','api_key':'synthetic-manyreach-key'}})


def transport(monkeypatch, response):
    requests = []
    original = httpx.AsyncClient
    def handle(request):
        requests.append(request)
        return response
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,body,query', [
    ('get_account',{},'GET','/account',None,{}),
    ('create_prospect',{'email':'jane@example.com','baseListId':10,'firstName':'Jane'},'POST','/prospects',{'email':'jane@example.com','baseListId':10,'firstName':'Jane'},{}),
    ('update_prospect',{'id':42,'sendingActive':False,'sendingStatus':'Interested'},'PATCH','/prospects/42',{'sendingActive':False,'sendingStatus':'Interested'},{}),
    ('create_campaign',{'name':'Outreach','subject':'Hello','body':'Welcome'},'POST','/campaigns',{'name':'Outreach','subject':'Hello','body':'Welcome'},{}),
    ('start_campaign',{'id':42},'POST','/campaigns/42/start',None,{}),
    ('pause_campaign',{'id':42},'POST','/campaigns/42/pause',None,{}),
    ('list_campaigns',{'page':2,'limit':20,'includeArchived':False},'GET','/campaigns',None,{'pageQuery.page':'2','pageQuery.limit':'20','pageQuery.includeArchived':'false'}),
    ('add_prospect_tag',{'id':42,'tagId':5},'POST','/prospects/42/tags',{'tagId':5},{}),
    ('check_blacklisted_email',{'email':'jane+sales@example.com'},'GET','/blacklist/emails/check',None,{'email':'jane+sales@example.com'}),
    ('delete_prospect',{'id':42},'DELETE','/prospects/42',None,{}),
])
async def test_exact_wire_and_response(monkeypatch,operation,config,method,path,body,query):
    expected = {'id':42,'title':'Example account'}
    requests = transport(monkeypatch,httpx.Response(200,json=expected))
    result = await node({'operation':operation,**config}).execute({})
    assert result['data'] == expected
    assert len(requests)==1
    req=requests[0]
    assert req.method==method and req.url.copy_with(query=None)==httpx.URL('https://api.manyreach.com/api/v2'+path)
    assert req.headers['X-API-Key']=='synthetic-manyreach-key'
    assert dict(req.url.params)==query
    assert (json.loads(req.content) if req.content else None)==body


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[302,401,403,422,429,500])
async def test_rejections_do_not_report_success_or_leak_key(monkeypatch,status):
    requests=transport(monkeypatch,httpx.Response(status,text='rejected synthetic-manyreach-key'))
    with pytest.raises(ValueError) as exc:
        await node({'operation':'get_account'}).execute({})
    assert str(status) in str(exc.value) and 'synthetic-manyreach-key' not in str(exc.value)
    assert len(requests)==1


@pytest.mark.asyncio
async def test_empty_delete_response(monkeypatch):
    transport(monkeypatch,httpx.Response(204))
    assert (await node({'operation':'delete_prospect','id':42}).execute({})) == {'data':None,'http_status':204}


@pytest.mark.parametrize('config',[{'operation':'get_prospect','id':0},{'operation':'create_prospect'},{'operation':'create_campaign'},{'operation':'add_prospect_tag','id':1,'tagId':0}])
def test_required_and_bounded_fields(config):
    with pytest.raises(ValueError):
        native.ManyreachNode.parse_config({'config':config})
