"""Requests use the published Customer API's example parameters."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import emaillistverify_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/emaillistverify/requests.json').read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='fixture', node_type='automation-emaillistverify', node_data={
        'config': config, 'credentials': {'credential_type': 'emaillistverify_api_key', 'api_key': 'synthetic-elv-key'}})

@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c:c['config']['operation'])
async def test_published_requests(monkeypatch, case):
    requests=[]
    def respond(req):
        requests.append(req)
        return httpx.Response(200,json={'credits': 100})
    original=httpx.AsyncClient
    monkeypatch.setattr(native.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    result=await node(case['config']).execute({})
    req=requests[0]
    assert result == {'status':'success','data':{'credits':100}}
    assert req.method==case['method'] and req.url.path==case['path']
    assert dict(req.url.params)==case['query']
    assert req.headers['x-api-key']=='synthetic-elv-key'
    assert req.url.host=='api.emaillistverify.com'
    if case['body']:assert json.loads(req.content)==case['body']

@pytest.mark.asyncio
@pytest.mark.parametrize('code', [301,401,403,429,500])
async def test_errors_are_not_success(monkeypatch,code):
    original=httpx.AsyncClient
    monkeypatch.setattr(native.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(code,json={'message':'Rejected synthetic-elv-key'})),**kw))
    result=await node({'operation':'get_credits'}).execute({})
    assert result['status']=='error' and result['http_status']==code
    assert 'synthetic-elv-key' not in str(result)

@pytest.mark.asyncio
async def test_plain_verification_result(monkeypatch):
    original=httpx.AsyncClient
    monkeypatch.setattr(native.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(200,text='ok')),**kw))
    assert (await node({'operation':'verify_email','email':'john.smith@gmail.com'}).execute({}))['data']=='ok'

@pytest.mark.asyncio
async def test_documented_credit_error(monkeypatch):
    original=httpx.AsyncClient
    monkeypatch.setattr(native.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(200,text='error_credit')),**kw))
    assert (await node({'operation':'verify_email','email':'john.smith@gmail.com'}).execute({})) == {'status':'error','error':'error_credit'}

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,extra', [('create_email_job', {'email':'john.smith@gmail.com'}),('get_email_job', {'id':'67fa2fb9eff3c4a985b4ee52'})])
async def test_documented_job_quality_is_preserved(monkeypatch, operation, extra):
    # The provider documents quality=high, despite incorrectly marking it email-formatted.
    body={'id':'67fa2fb9eff3c4a985b4ee52','email':'john.smith@gmail.com','quality':'high'}
    original=httpx.AsyncClient
    monkeypatch.setattr(native.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(201 if operation=='create_email_job' else 200,json=body)),**kw))
    assert (await node({'operation':operation,**extra}).execute({})) == {'status':'success','data':body}
