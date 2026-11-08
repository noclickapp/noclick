"""Exercise requests through the real factory against published v1 examples."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import enforcedflow_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

CASES = json.loads((Path(__file__).parent / 'fixtures/enforcedflow/requests.json').read_text())

@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c:c['config']['operation'])
async def test_contract_requests(monkeypatch, case):
    requests = []
    original = httpx.AsyncClient
    def reply(request):
        requests.append(request)
        return httpx.Response(case['status'], json=case['response'])
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(reply), **kw))
    node = NodeFactory.create_node(node_id='fixture', node_type='automation-enforcedflow', node_data={'config':case['config'], 'credentials':{'credential_type':'enforcedflow_provider_key','provider_key':'test-provider-key'}})
    result = await node.execute({})
    assert result == case['response']
    request, = requests
    assert request.method == case['method']
    assert request.url.path == '/api/v1/advanced-round-robin' + case['path']
    assert request.headers['Authorization'] == 'test-provider-key'
    assert dict(request.url.params) == case.get('params', {})
    assert (json.loads(request.content) if request.content else None) == case.get('body')

@pytest.mark.asyncio
async def test_rejected_key_is_redacted(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda r:httpx.Response(401,text='Rejected test-provider-key')),**kw))
    node = NodeFactory.create_node(node_id='fixture', node_type='automation-enforcedflow', node_data={'config':{'operation':'list_groups'},'credentials':{'credential_type':'enforcedflow_provider_key','provider_key':'test-provider-key'}})
    with pytest.raises(ValueError,match=r'HTTP 401: Rejected \[redacted\]'):
        await node.execute({})
