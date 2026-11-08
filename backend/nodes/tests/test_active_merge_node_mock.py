"""HTTP-boundary coverage for every Active Merge operation; no account calls."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import active_merge_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/active-merge/operations.json').read_text())
TOKEN = 'synthetic-active-merge-api-key'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='active-merge-test', node_type='automation-active-merge',
        node_data={'config': config, 'credentials': {'credential_type':'active_merge_api_key', 'api_key':TOKEN}})

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_active_merge_wire_contract(operation, monkeypatch):
    case = CASES[operation]
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == case['method']
        assert request.url.host == 'app.activemerge.com'
        assert request.headers['API-KEY'] == TOKEN
        expected = case['path']
        for key,value in case['config'].items():
            expected = expected.replace('{'+key+'}', str(value))
        assert request.url.path == expected
        if request.method == 'POST' and request.content:
            body = json.loads(request.content)
            assert body == {k:v for k,v in case['config'].items() if k != 'operation'}
        return httpx.Response(200, json=case['response'])
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert result['data'] == case['response']
    assert len(calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401,403,422,429,500])
async def test_active_merge_error_no_secret_or_retry(status, monkeypatch):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(status, text=TOKEN)
    monkeypatch.setattr(native,'guarded_async_client',lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(respond),**kw))
    result=await node({'operation':'get_credits'}).execute({})
    assert result['status']=='error' and result['http_status']==status
    assert TOKEN not in str(result) and len(calls)==1

@pytest.mark.parametrize('value', ['', 'https://example.com/key', 'a\nb'])
def test_active_merge_invalid_key(value):
    with pytest.raises(ValidationError):
        native.ActiveMergeAPIKeyCredential(api_key=value)


def test_active_merge_signature_source_required():
    with pytest.raises(ValidationError):
        native.CreateSignatureRequest(signers=[{'email':'jane@acme.com'}])

@pytest.mark.asyncio
async def test_active_merge_signature_pagination(monkeypatch):
    payload={'data':[], 'meta':{'current_page':2,'last_page':3,'total':52}}
    def respond(request):
        assert dict(request.url.params)=={'status':'sent','page':'2'}
        return httpx.Response(200,json=payload)
    monkeypatch.setattr(native,'guarded_async_client',lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(respond),**kw))
    result=await node({'operation':'list_signature_requests','status':'sent','page':2}).execute({})
    assert result['data']['meta']==payload['meta']

@pytest.mark.asyncio
async def test_active_merge_path_traversal_refused():
    with pytest.raises(ValueError, match='single resource ID'):
        await node({'operation':'get_template_placeholders','id':'../user/credits'}).execute({})

@pytest.mark.asyncio
async def test_active_merge_malformed_credit_evidence_is_unverified(monkeypatch):
    monkeypatch.setattr(native,'guarded_async_client',lambda **kw:httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={})),**kw))
    with pytest.raises(ValueError, match='could not be confirmed'):
        await node({'operation':'get_credits'}).execute({})
