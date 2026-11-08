"""Replay published request/response examples through the native execution seam."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes import redirect_pizza_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/redirect-pizza/contract_examples.json').read_text())
AUTH = {'credential_type': 'redirect_pizza_api_token', 'api_token': 'rpa_fixture_token_for_tests'}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_redirect_pizza_documented_examples(operation, monkeypatch):
    case = EXAMPLES[operation]
    requests = []
    async def send(request):
        requests.append(request)
        assert request.url.host == 'redirect.pizza'
        assert request.method == case['method']
        path = case['path']
        for key, value in case['config'].items():
            path = path.replace('{'+key+'}', str(value))
        assert request.url.path == path
        assert request.headers['Authorization'] == 'Bearer ' + AUTH['api_token']
        if request.method in {'PUT', 'POST'} and request.content:
            payload = json.loads(request.content)
            for key in ('sources', 'destination', 'redirect_type', 'alias', 'domain'):
                if key in payload:
                    assert payload[key] == case['config'][key]
        return httpx.Response(204) if case['response'] is None else httpx.Response(200, json=case['response'])
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    result = await run_node_operation(node_type='automation-redirect-pizza', operation=operation,
        arguments=case['config'], credential_data=AUTH, user_id='00000000-0000-4000-8000-000000000001')
    assert len(requests) == 1
    assert result == (case['response'] if case['response'] is not None else {'success': True})

@pytest.mark.parametrize('value', [0, -1, '../team', '1/../team'])
def test_redirect_pizza_rejects_unsafe_ids(value):
    with pytest.raises(ValidationError):
        node.GetRedirect(id=value)

@pytest.mark.asyncio
async def test_redirect_pizza_rejection_redacts_token(monkeypatch):
    async def send(request):
        return httpx.Response(401, json={'message': 'Rejected ' + AUTH['api_token']})
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    with pytest.raises(ValueError, match='Rejected') as exc:
        await run_node_operation(node_type='automation-redirect-pizza', operation='list_redirects', arguments={}, credential_data=AUTH, user_id='00000000-0000-4000-8000-000000000001')
    assert AUTH['api_token'] not in str(exc.value)
