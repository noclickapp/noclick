"""Exercise every Certifier route and request against published contract examples.
Negative cases verify rejected tokens, API errors, and empty delete responses.
"""
import json
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes.core.registry import NodeFactory
from nodes.certifier_node import CertifierNode, CertifierTokenCredential

CASES = json.loads((Path(__file__).parent / 'fixtures/certifier/operations.json').read_text())
TOKEN = 'certifier-test-access-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    # This node uses only HTTP, so the database fixture has no work to perform.
    yield

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_contract_requests(monkeypatch, operation):
    case = CASES[operation]
    calls = []
    async def handle(request):
        calls.append(request)
        assert request.method == case['method']
        assert request.url.path == case['path']
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN
        assert request.headers['Certifier-Version'] == '2022-10-26'
        values = {k:v for k,v in case['config'].items() if k not in {'operation','id'}}
        if case['method'] in {'POST','PATCH'} and values:
            sent = json.loads(request.content)
            if 'triggeredAt' in values:
                assert datetime.fromisoformat(sent.pop('triggeredAt')) == datetime.fromisoformat(values.pop('triggeredAt'))
            assert sent == values
        else:
            assert dict(request.url.params) == {k:str(v) for k,v in values.items()}
        return httpx.Response(case['status'], json=case['response']) if case['response'] is not None else httpx.Response(204)
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c:
            yield c
    monkeypatch.setattr('nodes.certifier_node.guarded_async_client', client)
    node = NodeFactory.create_node(node_type='automation-certifier', node_id='certifier-test', node_data={'config':case['config'], 'credentials':{'credential_type':'certifier_api_token','api_token':TOKEN}})
    node.emit = AsyncMock()
    result = await node.execute({})
    assert len(calls) == 1
    expected = case['response']
    if expected is None:
        expected = {'deleted':True,'id':case['config']['id']}
    elif isinstance(expected, list):
        expected = {'data':expected}
    assert result == expected

@pytest.mark.parametrize('token', ['Bearer abc','abc\nheader','https://example.com/token'])
def test_invalid_token(token):
    with pytest.raises((ValidationError, ValueError)):
        CertifierTokenCredential(api_token=token)

@pytest.mark.parametrize('operation', ['get_credential', 'delete_group'])
def test_path_injection(operation):
    with pytest.raises(ValueError):
        CertifierNode.parse_config({'config':{'operation':operation,'id':'../other'}, 'credentials':{'api_token':TOKEN}})

@pytest.mark.asyncio
async def test_error_message_redacts_token(monkeypatch):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(401,json={'error':{'message':'Denied '+TOKEN}}))) as c:
            yield c
    monkeypatch.setattr('nodes.certifier_node.guarded_async_client', client)
    node = NodeFactory.create_node(node_type='automation-certifier', node_id='bad', node_data={'config':{'operation':'list_groups'},'credentials':{'api_token':TOKEN}})
    with pytest.raises(ValueError, match=r'Denied \[redacted\]'):
        await node.execute({})
