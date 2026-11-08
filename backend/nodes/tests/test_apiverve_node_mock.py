"""Exercise requests and parsing using provider-authored examples.

The fixtures retain documented inputs and responses, including generated assets.
"""
import json
from pathlib import Path
from contextlib import asynccontextmanager
import httpx
import pytest
from nodes.apiverve_node import ApiverveNode
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/apiverve/documented.json').read_text())

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_documented_request_and_response(operation, monkeypatch):
    example = EXAMPLES[operation]
    def handle(request):
        assert request.method == example['method']
        assert request.url.host == 'api.apiverve.com'
        assert request.url.path == example['path']
        assert request.headers['x-api-key'] == 'test-secret-key'
        if request.method == 'POST':
            assert json.loads(request.content) == example['params']
        else:
            assert dict(request.url.params) == {k: str(v) for k, v in example['params'].items()}
        return httpx.Response(200, json=example['response'])
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as session:
            yield session
    monkeypatch.setattr('nodes.apiverve_node.guarded_async_client', client)
    node = NodeFactory.create_node(node_id='test', node_type='automation-apiverve', node_data={'config': example['config'], 'credentials': {'api_key': 'test-secret-key'}})
    result = await node.execute({})
    assert result == {'status': 'success', 'data': example['response']['data']}

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'status':'error','error':'Invalid API key'}, {'status':'ok','error':'Out of credits'}])
async def test_error_envelope_is_never_success(body, monkeypatch):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=body))) as session:
            yield session
    monkeypatch.setattr('nodes.apiverve_node.guarded_async_client', client)
    node = NodeFactory.create_node(node_id='test', node_type='automation-apiverve', node_data={'config': {'operation':'list_currency_symbols'}, 'credentials': {'api_key':'test-secret-key'}})
    assert (await node.execute({}))['status'] == 'error'
