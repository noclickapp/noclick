"""Workiz's published examples through the production operation runner."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import workiz_node as node
from nodes.core.run_op import run_node_operation

CASES = json.loads((Path(__file__).parent / 'fixtures/workiz/contract_examples.json').read_text())['cases']
AUTH = {'credential_type': 'workiz_api_token', 'api_token': 'fixture-workiz-secret'}

@pytest.fixture
def ensure_native_db_pool():
    yield

async def run(config):
    return await run_node_operation(node_type='automation-workiz', operation=config['operation'],
        arguments={k: v for k, v in config.items() if k != 'operation'}, credential_data=AUTH,
        user_id='00000000-0000-4000-8000-000000000001')

@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_published_contract_requests_and_responses(monkeypatch, case):
    requests = []
    def send(request):
        requests.append(request)
        assert request.method == case['method']
        path = case['path']
        for field in case['path_fields']:
            path = path.replace('{' + field + '}', case['config'][field])
        assert str(request.url).startswith('https://api.workiz.com/crm/api' + path)
        assert request.headers['Authorization'] == 'Bearer ' + AUTH['api_token']
        assert AUTH['api_token'] not in str(request.url)
        if request.method in {'POST', 'PUT'}:
            expected = {k: v for k, v in case['config'].items() if k not in {'operation', *case['path_fields'], *case['query_fields']}}
            assert (json.loads(request.content) if request.content else {}) == expected
        return httpx.Response(case['status'], json=case['response']) if case['response'] is not None else httpx.Response(case['status'])
    native = httpx.AsyncClient
    monkeypatch.setattr(node.httpx, 'AsyncClient', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    result = await run(case['config'])
    assert result['status'] == 'success'
    assert len(requests) == 1
    if isinstance(case['response'], dict):
        assert result['data'] == case['response']

@pytest.mark.parametrize('code', [401, 403, 429, 500])
async def test_provider_errors_are_explicit_and_not_retried(monkeypatch, code):
    requests = []
    def send(request):
        requests.append(request)
        return httpx.Response(code, json={'message': 'Rejected ' + AUTH['api_token']})
    native = httpx.AsyncClient
    monkeypatch.setattr(node.httpx, 'AsyncClient', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    result = await run({'operation': 'list_clients'})
    assert result['status'] == 'error' and result['http_status'] == code
    assert AUTH['api_token'] not in json.dumps(result)
    assert len(requests) == 1

@pytest.mark.parametrize('identifier', ['../evil', 'https://evil.test', 'a?x=1', 'a/b', 'a%2Fb'])
def test_path_injection_is_rejected(identifier):
    with pytest.raises(ValueError):
        node.WorkizNode.parse_config({'config': {'operation': 'get_job', 'id': identifier}, 'credentials': AUTH})
