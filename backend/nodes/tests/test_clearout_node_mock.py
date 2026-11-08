"""Exercise Clearout through the native execution seam with intercepted HTTP.
Request assertions cover routing, authentication, query/body placement and errors.
"""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import clearout_node as module
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "clearout_api_token", "api_token": "fixture-secret-key"}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.clearout.io"
        assert request.headers["Authorization"] == "Bearer fixture-secret-key"
        assert AUTH['api_token'] not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(module, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies

async def run(op, args=None):
    return await run_node_operation(node_type='automation-clearout', operation=op,
        arguments=args or {}, credential_data=AUTH,
        user_id='00000000-0000-4000-8000-000000000001')

CASES = [
    ('verify_email', {'email':'valid@example.com','timeout':10000}, 'POST', '/email_verify/instant'),
    ('find_email', {'name':'Steven Morris','domain':'apple.com','queue':False}, 'POST', '/email_finder/instant'),
    ('get_verification_status', {'list_id':'5d076c8e3b53f9b0f3cf6abb'}, 'GET', '/email_verify/bulk/progress_status'),
    ('get_finder_status', {'qid':'61008c4597947d45700f4bb2'}, 'GET', '/email_finder/instant/queue_status'),
    ('cancel_verification', {'list_id':'5d076c8e3b53f9b0f3cf6abb'}, 'POST', '/email_verify/list/cancel'),
    ('remove_finder_list', {'list_id':'5d076c8e3b53f9b0f3cf6abb','ignore_result':True}, 'POST', '/email_finder/list/remove'),
    ('list_finder_jobs', {'limit':10,'start_after':'69dd35c3b8933b51437ad3ab'}, 'POST', '/email_finder/list'),
    ('get_credits', {}, 'GET', '/account/credits'),
]

@pytest.mark.asyncio
@pytest.mark.parametrize('op,args,method,path', CASES)
async def test_request_and_response(transport, op, args, method, path):
    requests, replies = transport
    body = {'status':'success','data':{'fixture':'preserved'}}
    replies.append((200, body))
    assert await run(op,args) == body
    assert len(requests)==1
    req=requests[0]
    assert req.method==method
    assert req.url.path=='/v2'+path
    sent=dict(req.url.params) if method=='GET' else json.loads(req.content)
    for key,value in args.items():
        assert sent[key] == (str(value) if method=='GET' else value)

@pytest.mark.asyncio
@pytest.mark.parametrize('code', [401,429,524])
async def test_error_is_preserved_without_retry(transport, code):
    requests,replies=transport
    error={'status':'failed','error':{'message':'provider rejection'}}
    replies.append((code,error))
    result=await run('get_credits')
    assert result['status']=='error'
    assert result['error']==error
    assert len(requests)==1

@pytest.mark.asyncio
async def test_application_error_preserved(transport):
    _,replies=transport
    body={'status':'failed','error':{'message':'not enough credits'}}
    replies.append((200,body))
    assert await run('get_credits')==body

@pytest.mark.parametrize('operation,args', [('verify_email',{}),('find_email',{'name':'Steven Morris'}),('list_finder_jobs',{'limit':101})])
def test_required_fields_and_bounds(operation,args):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        module.ClearoutFullConfig(config={'operation':operation,**args},credentials=AUTH)

@pytest.mark.asyncio
@pytest.mark.parametrize('op,key,args', [
    ('find_mx','POST /domain/resolve/mx',{'domain':'gmail.com'}),
    ('find_whois','POST /domain/resolve/whois',{'domain':'apple.com'}),
    ('find_company_domains','GET /public/companies/autocomplete',{'query':'amazon'}),
])
async def test_published_response_bodies(transport,op,key,args):
    from pathlib import Path
    examples=json.loads((Path(__file__).parent/'fixtures/clearout/published_responses.json').read_text())
    body=examples[key]['body']
    requests,replies=transport
    replies.append((200,body))
    assert await run(op,args)==body
    path=key.split(' ',1)[1]
    assert requests[0].url.path == (path if op=='find_company_domains' else '/v2'+path)
