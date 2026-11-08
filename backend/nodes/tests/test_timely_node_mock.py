"""Execute every Timely operation against published response examples."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import timely_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/timely/contract.json').read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c:c['operation'])
async def test_published_contract(monkeypatch, case):
    seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(case['status'], json=case['body']) if case['body'] is not None else httpx.Response(case['status'])
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(respond), **kw))
    node=NodeFactory.create_node(node_id='timely-test',node_type='automation-timely',node_data={'config':case['config'],'credentials':{'credential_type':'timely_token','access_token':'synthetic-token','account_id':1}})
    result=await node.execute({})
    assert result['status']=='success'
    request=seen[0]
    assert request.method==case['method'] and request.url.path==case['path']
    assert request.headers['Authorization']=='Bearer synthetic-token'
    if case['operation'].startswith(('create_','update_')):
        key='client' if 'client' in case['operation'] else 'project' if 'project' in case['operation'] else 'event'
        sent=json.loads(request.content)
        assert sent[key]['name' if key!='event' else 'day']==case['config']['name' if key!='event' else 'day']
    assert 'synthetic-token' not in str(result)

@pytest.mark.asyncio
@pytest.mark.parametrize('status',[301,401,403,429,500])
async def test_rejected_read(monkeypatch,status):
    monkeypatch.setattr(native,'guarded_async_client',lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(status,text='Denied')),**kw))
    node=NodeFactory.create_node(node_id='timely-test',node_type='automation-timely',node_data={'config':{'operation':'get_current_user'},'credentials':{'credential_type':'timely_token','access_token':'synthetic-token','account_id':1}})
    result=await node.execute({})
    assert result['status']=='error' and result['http_status']==status
