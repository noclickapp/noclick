"""Exercise native Basin requests through the real node factory, without accounts."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import basin_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/basin/requests.json').read_text())
TOKEN = 'synthetic-basin-key-42'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='basin-fixture', node_type='automation-basin',
        node_data={'config': config, 'credentials': {'credential_type':'basin_api_key','api_key':TOKEN}})


def transport(monkeypatch, response):
    seen=[]
    def respond(request):
        seen.append(request)
        return response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return seen

@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c:c['config']['operation'])
async def test_contract_request(monkeypatch, case):
    reply={'id':123,'name':'Example Form'}
    seen=transport(monkeypatch,httpx.Response(200,json=reply))
    result=await node(case['config']).execute({})
    assert result['status']=='success' and result['data']==reply
    assert len(seen)==1
    request=seen[0]
    assert request.url.host=='usebasin.com'
    assert request.method==case['method'] and request.url.path==case['path']
    assert request.headers['authorization']=='Token '+TOKEN
    assert dict(request.url.params)=={}
    assert (json.loads(request.content) if request.content else None)==case['body']

@pytest.mark.asyncio
async def test_filters_and_single_page_envelope(monkeypatch):
    payload={'forms':[{'id':123,'name':'Contact'}], 'pagination':{'next_page':3}}
    seen=transport(monkeypatch,httpx.Response(200,json=payload))
    result=await node({'operation':'list_forms','page':'2','query':'Contact + sales'}).execute({})
    assert dict(seen[0].url.params)=={'page':'2','query':'Contact + sales'}
    assert result['data']==payload and result['page_scope']=='single_provider_page'

@pytest.mark.asyncio
@pytest.mark.parametrize('status,body',[(401,{'error':'Invalid token'}),(403,{'error':'Forbidden'}),(422,{'errors':['invalid']}),(200,{'success':False,'error':'Rejected'})])
async def test_provider_errors_are_not_success(monkeypatch,status,body):
    transport(monkeypatch,httpx.Response(status,json=body))
    result=await node({'operation':'list_forms'}).execute({})
    assert result['status']=='error'

@pytest.mark.asyncio
async def test_empty_delete_response_and_secret_redaction(monkeypatch):
    transport(monkeypatch,httpx.Response(204))
    assert (await node({'operation':'delete_submission','id':'123'}).execute({}))['data'] is None
    transport(monkeypatch,httpx.Response(200,json={'value':TOKEN}))
    assert TOKEN not in str(await node({'operation':'list_forms'}).execute({}))

@pytest.mark.asyncio
async def test_malformed_response_and_redirect_not_followed(monkeypatch):
    transport(monkeypatch,httpx.Response(200,text='<html>Oops</html>'))
    assert (await node({'operation':'list_forms'}).execute({}))['status']=='error'
    seen=transport(monkeypatch,httpx.Response(302,headers={'Location':'https://example.com'}))
    assert (await node({'operation':'list_forms'}).execute({}))['status']=='error'
    assert len(seen)==1

@pytest.mark.parametrize('identifier',['../forms','a/b','a?b','a#b'])
def test_path_injection_refused(identifier):
    with pytest.raises(ValueError):
        node({'operation':'get_form','id':identifier})
