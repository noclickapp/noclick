"""Bluebarry HTTP contract regressions without live credentials."""
import json
import httpx
import pytest
from nodes import bluebarry_node as native
from nodes.core.registry import NodeFactory

ID = '64238d01-d402-474b-8c2d-fbc957e9d290'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='bluebarry-test', node_type='automation-bluebarry', node_data={
        'config':config, 'credentials':{'credential_type':'bluebarry_api_key','api_key':'synthetic-test-key','tenant_id':'synthetic-tenant'}})

def intercept(monkeypatch, status, body):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.host == 'data.bluebarry.ai'
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,resource', native.READS.items())
async def test_reads(monkeypatch, operation, resource):
    body = {'value':[{'id':ID,'email':'shopper@example.com'}], '@odata.count':200, '@odata.nextLink':'https://data.bluebarry.ai/data/Identities?$skip=100'}
    requests = intercept(monkeypatch, 200, body)
    result = await node({'operation':operation,'top':20,'skip':40,'select':'id,createdDate'}).execute({})
    assert result['data'] == body
    request = requests[0]
    assert request.method == 'GET' and request.url.path == '/data/' + resource
    assert request.headers['Authorization'] == 'synthetic-test-key'
    assert 'BB-Tenant-Id' not in request.headers
    assert request.url.params['$top'] == '20' and request.url.params['$skip'] == '40'
    assert request.url.params['$select'] == 'id,createdDate'
    assert ('$count' in request.url.params) == (operation != 'list_past_results')
    assert len(requests) == 1

@pytest.mark.asyncio
async def test_create_webhook(monkeypatch):
    requests = intercept(monkeypatch, 201, {'id':ID,'topic':'result.viewed','url':'https://example.com/hook'})
    await node({'operation':'create_webhook','topic':'result.viewed','url':'https://example.com/hook'}).execute({})
    assert requests[0].method == 'POST' and requests[0].url.path == '/data/WebhookSubscriptions'
    assert json.loads(requests[0].content) == {'topic':'result.viewed','url':'https://example.com/hook','disabled':False}

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,path,status,body', [
    ('delete_webhook', f'/data/WebhookSubscriptions({ID})', 204, None),
    ('issue_signing_secret', f'/data/WebhookSubscriptions/{ID}/signing-secret', 200, {'signingSecret':'example-signing-secret'})])
async def test_webhook_mutations(monkeypatch, operation, path, status, body):
    requests = intercept(monkeypatch, status, body)
    result = await node({'operation':operation,'id':ID}).execute({})
    assert requests[0].url.path == path
    assert requests[0].method == ('DELETE' if status == 204 else 'POST')
    assert result['data'] == body

@pytest.mark.asyncio
async def test_identify_uses_tenant_not_key(monkeypatch):
    requests = intercept(monkeypatch, 204, None)
    result = await node({'operation':'identify_shopper','email':'shopper@example.com','user_id':ID,'session_id':ID}).execute({})
    assert result['http_status'] == 204
    assert requests[0].url.path == '/data/identify'
    assert requests[0].headers['BB-Tenant-Id'] == 'synthetic-tenant'
    assert 'Authorization' not in requests[0].headers
    assert json.loads(requests[0].content) == {'email':'shopper@example.com','userId':ID,'sessionId':ID}

@pytest.mark.asyncio
async def test_rejection_and_malformed_page_fail(monkeypatch):
    intercept(monkeypatch, 401, {})
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation':'list_identities'}).execute({})
    intercept(monkeypatch, 200, {'value':{}})
    with pytest.raises(ValueError, match='OData'):
        await node({'operation':'list_identities'}).execute({})
