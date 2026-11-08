"""Exercise the native node factory through HTTP with all public operations."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import quote
import httpx
import pytest
from nodes import airtop_node as node
from nodes.core.run_op import run_node_operation

CASES = json.loads((Path(__file__).parent / 'fixtures/airtop/operations.json').read_text())
AUTH = {'credential_type': 'airtop_api_key', 'api_key': 'fixture-airtop-secret'}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    original = httpx.AsyncClient
    async def send(request):
        requests.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)
    monkeypatch.setattr(node.httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(send)))
    return requests, replies

async def run(operation, config):
    return await run_node_operation(node_type='automation-airtop', operation=operation,
        arguments=config, credential_data=AUTH, user_id='00000000-0000-4000-8000-000000000001')

@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c:c['operation'])
async def test_operations(case, wire):
    requests, replies = wire
    body = {'meta': {'requestId':'fixture'}, 'data': {'id':'fixture-resource'}, 'errors':None, 'warnings':None}
    replies.append((200,body))
    result = await run(case['operation'],case['config'])
    assert result == body
    assert len(requests) == 1
    req = requests[0]
    method,path,mapping = node.ROUTES[case['operation']]
    assert req.method == case['method'] == method
    expected_body = {}
    for field,value in case['config'].items():
        destination,key = mapping[field]
        if destination == 'path':path=path.replace('{'+key+'}',quote(str(value),safe=''))
        elif destination == 'body':expected_body[key]=value
    assert req.url.path == '/api'+path
    assert req.headers['Authorization'] == 'Bearer '+AUTH['api_key']
    assert AUTH['api_key'] not in str(req.url)
    if method == 'POST':assert json.loads(req.content) == expected_body

@pytest.mark.asyncio
async def test_pagination(wire):
    requests,replies=wire
    replies.append((200,{'data':{'sessions':[], 'pagination':{'offset':10,'limit':5}},'errors':None}))
    await run('list_sessions',{'offset':10,'limit':5,'status':'running'})
    assert dict(requests[0].url.params)=={'status':'running','offset':'10','limit':'5'}

@pytest.mark.asyncio
@pytest.mark.parametrize('status,body',[(401,{'message':'Rejected'}),(200,{'errors':[{'message':'Failed'}]}),(302,{'message':'Moved'})])
async def test_errors_are_failures(wire,status,body):
    requests,replies=wire
    replies.append((status,body))
    with pytest.raises(ValueError):await run('list_sessions',{})
    assert len(requests)==1

@pytest.mark.asyncio
async def test_required_prompt_before_network(wire):
    with pytest.raises(Exception):await run('query_page',{'session_id':'s','window_id':'w'})
    assert wire[0]==[]
