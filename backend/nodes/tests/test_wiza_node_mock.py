"""Offline Wiza request and response regressions; no live account is used."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import TypeAdapter, ValidationError
from nodes import wiza_node as wiza
from nodes.core.registry import NodeFactory

CONFIGS = json.loads((Path(__file__).parent / 'fixtures/wiza/configs.json').read_text())
CONTRACT = json.loads((Path(__file__).parent / 'fixtures/wiza/documented_contract.json').read_text())
TOKEN = 'synthetic-wiza-api-key'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='wiza-test', node_type='automation-wiza', node_data={
        'config': config, 'credentials': {'credential_type':'wiza_api_key', 'api_key':TOKEN}})

def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c
    monkeypatch.setattr(wiza, 'guarded_async_client', client)

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(CONFIGS))
async def test_each_operation_uses_one_published_endpoint(monkeypatch, operation):
    seen = []
    def handler(request):
        seen.append(request)
        assert request.url.host == 'wiza.co'
        assert request.headers['authorization'] == 'Bearer ' + TOKEN
        return httpx.Response(200, json={'credits': {'api_credits':100}, 'data': {'id':123}, 'status': {'code':200}})
    transport(monkeypatch, handler)
    n = node(CONFIGS[operation]); n.emit = AsyncMock()
    result = await n.execute({})
    assert result['status'] == 'success'
    assert len(seen) == 1
    expected = CONTRACT['operations'][operation]
    assert seen[0].method == expected['method']
    assert seen[0].url.path == expected['path'].replace('{id}', '123')
    if operation == 'get_list_contacts':
        assert dict(seen[0].url.params) == {'segment':'people'}
    if operation == 'start_individual_reveal':
        assert json.loads(seen[0].content)['individual_reveal'] == {'profile_url':'https://www.linkedin.com/in/stephen-hakami-5babb21b0/'}
    if operation == 'create_list':
        assert json.loads(seen[0].content)['list']['items'] == [{'full_name':'Stephen Hakami','company':'Wiza','domain':'wiza.co'}]
    if operation == 'continue_prospect_search':
        assert json.loads(seen[0].content) == {'id':123,'max_profiles':10}

@pytest.mark.asyncio
@pytest.mark.parametrize('http_status', [200, 401, 403, 429, 500])
async def test_provider_errors_preserve_rejection_and_redact_token(monkeypatch, http_status):
    transport(monkeypatch, lambda r: httpx.Response(http_status, json={'status':{'code':401,'message':'Unauthorized ' + TOKEN}}))
    n = node(CONFIGS['get_credits']); n.emit = AsyncMock()
    result = await n.execute({})
    assert result['status'] == 'error'
    assert result['message'] == 'Unauthorized [redacted]'

@pytest.mark.asyncio
async def test_company_pagination_sends_only_token_and_size(monkeypatch):
    def handler(request):
        assert json.loads(request.content) == {'page_token':'opaque-company-page','size':10}
        return httpx.Response(200,json={'data':[],'page_token':None})
    transport(monkeypatch,handler)
    n=node({'operation':'search_companies','page_token':'opaque-company-page'}); n.emit=AsyncMock()
    assert (await n.execute({}))['data']['page_token'] is None

@pytest.mark.parametrize('config', [
    {'operation':'start_individual_reveal','contact_json':'{}'},
    {'operation':'start_individual_reveal','contact_json':'{"email":"a@b.test","profile_url":"https://linkedin.com/in/a"}'},
    {'operation':'create_list','name':'Empty','items_json':'[]'},
    {'operation':'search_prospects','filters_json':'{"unknown":1}'},
    {'operation':'search_companies','filters_json':'{}'},
    {'operation':'search_companies','filters_json':'{"company_industry":["Computer Software"]}','page_token':'abc'},
    {'operation':'get_list','id':'../other'},
    {'operation':'get_list_contacts','id':'123','segment':'invalid'},
    {'operation':'enrich_company'},
    {'operation':'search_locations','query':'ab'},
])
def test_invalid_inputs_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        TypeAdapter(wiza.Operation).validate_python(config)

@pytest.mark.asyncio
@pytest.mark.parametrize('status,content', [(200,b'not JSON'),(200,b'[]'),(200,b'{}'),(302,b'{}')])
async def test_invalid_response_is_not_success(monkeypatch,status,content):
    transport(monkeypatch,lambda r:httpx.Response(status,content=content))
    n=node(CONFIGS['get_credits']); n.emit=AsyncMock()
    with pytest.raises(ValueError):
        await n.execute({})


@pytest.mark.asyncio
async def test_published_credit_response_preserved(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json=CONTRACT['credits_response']))
    n=node(CONFIGS['get_credits']); n.emit=AsyncMock()
    assert (await n.execute({}))['data'] == CONTRACT['credits_response']


@pytest.mark.asyncio
async def test_start_job_preserves_processing_status_without_retry(monkeypatch):
    seen=[]
    payload={'status':{'code':200,'message':''},'data':{'id':123,'status':'queued'}}
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json=payload)
    transport(monkeypatch,handler)
    n=node(CONFIGS['start_individual_reveal']); n.emit=AsyncMock()
    assert (await n.execute({}))['data'] == payload
    assert len(seen) == 1
