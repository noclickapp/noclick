"""Exercise the real node and HTTP boundary with synthetic Nozbe records."""
import json
import httpx
import pytest
from nodes import nozbe_teams_node as native
from nodes.core.registry import NodeFactory

ID = 'aBcDeFgH12345678'
TOKEN = 'synthetic-nozbe-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='nozbe-test', node_type='automation-nozbe-teams',
        node_data={'config': config, 'credentials': {'credential_type': 'nozbe_teams_api_token', 'api_token': TOKEN}})

def mock(monkeypatch, response):
    requests = []
    def respond(req):
        requests.append(req)
        return response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,method,path,fields', [
    ('list_teams','GET','/teams',{}), ('get_team','GET','/teams/'+ID,{'team_id':ID}),
    ('list_projects','GET','/projects',{}), ('get_project','GET','/projects/'+ID,{'project_id':ID}),
    ('list_tasks','GET','/tasks',{'project_id':ID}), ('get_task','GET','/tasks/'+ID,{'task_id':ID}),
    ('create_task','POST','/tasks',{'name':'My first task created via API'}),
    ('update_task','PUT','/tasks/'+ID,{'task_id':ID,'ended_at':1700000000000}),
    ('delete_task','DELETE','/tasks/'+ID,{'task_id':ID}),
    ('list_comments','GET','/comments',{'task_id':ID}), ('get_comment','GET','/comments/'+ID,{'comment_id':ID}),
    ('create_comment','POST','/comments',{'task_id':ID,'body':'Hello'}),
    ('update_comment','PUT','/comments/'+ID,{'comment_id':ID,'body':'Updated'}),
    ('delete_comment','DELETE','/comments/'+ID,{'comment_id':ID}),
    ('list_tags','GET','/tags',{}), ('get_tag','GET','/tags/'+ID,{'tag_id':ID}),
    ('create_tag','POST','/tags',{'name':'Work'}), ('update_tag','PUT','/tags/'+ID,{'tag_id':ID,'name':'Home'}),
])
async def test_operation_http_contract(monkeypatch, operation, method, path, fields):
    data = [{'id': ID, 'name':'Example'}] if operation.startswith('list_') else {'id':ID,'name':'Example'}
    requests = mock(monkeypatch, httpx.Response(201 if method=='POST' else 200, json=data))
    result = await node({'operation': operation, **fields}).execute({})
    assert result['status']=='success'
    request, = requests
    assert request.method == method and request.url.path == '/v1/api'+path
    assert request.headers['Authorization'] == TOKEN
    if method in {'POST','PUT'}:
        path_key = next((key for key in fields if '{'+key+'}' in native.ROUTES[operation][1]), None)
        assert json.loads(request.content) == {k:v for k,v in fields.items() if k!=path_key}
    assert TOKEN not in str(result)

@pytest.mark.asyncio
async def test_pagination_and_sort(monkeypatch):
    requests=mock(monkeypatch,httpx.Response(200,json=[{'id':ID}]))
    result=await node({'operation':'list_tasks','limit':1,'offset':20,'sort_by':'created_at'}).execute({})
    assert result['next_offset']==21
    assert dict(requests[0].url.params)=={'limit':'1','offset':'20','sortBy':'created_at'}

@pytest.mark.asyncio
async def test_clear_due_date_and_204(monkeypatch):
    requests=mock(monkeypatch,httpx.Response(200,json={'id':ID,'due_at':None}))
    await node({'operation':'update_task','task_id':ID,'due_at':None}).execute({})
    assert json.loads(requests[0].content)=={'due_at':None}
    mock(monkeypatch,httpx.Response(200))
    assert (await node({'operation':'delete_task','task_id':ID}).execute({}))['data'] is None

@pytest.mark.asyncio
async def test_rejection_and_bad_shape(monkeypatch):
    mock(monkeypatch,httpx.Response(401,text='Unauthorized'))
    result=await node({'operation':'list_teams'}).execute({})
    assert result['status']=='error' and result['http_status']==401
    mock(monkeypatch,httpx.Response(200,json={}))
    with pytest.raises(ValueError,match='invalid list'):
        await node({'operation':'list_teams'}).execute({})

@pytest.mark.parametrize('fields', [{'name':None}, {'project_id':None}, {'is_all_day':None}])
def test_nonnullable_task_fields(fields):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        native.UpdateTask(task_id=ID, **fields)
