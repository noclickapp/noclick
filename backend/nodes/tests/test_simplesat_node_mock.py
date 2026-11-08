"""Exercise native Simplesat execution with published request examples.

Transport interception verifies the actual headers, routes, JSON and pagination
without a provider account or live writes.
"""
import json
from pathlib import Path

import httpx
import pytest
from nodes.core.base import ConfigValidationError
from nodes import simplesat_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/simplesat/operations.json").read_text())
TOKEN = "synthetic-simplesat-key"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id="simplesat-test", node_type="automation-simplesat", node_data={
        "config": config, "credentials": {"credential_type": "simplesat_api_key", "api_key": TOKEN}})

@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c['config']['operation'])
async def test_published_operations(monkeypatch, case):
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(200, json=case['response'])
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    result = await node(case['config']).execute({})
    assert result == {'status': 'success', 'data': case['response']}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case['method']
    assert request.url.host == 'api.simplesat.io' and request.url.path == case['path']
    assert dict(request.url.params) == {k: str(v) for k,v in case['query'].items()}
    assert request.headers['X-Simplesat-Token'] == TOKEN
    if case['body'] is not None:
        assert json.loads(request.content) == case['body']
    else:
        assert not request.content

@pytest.mark.asyncio
async def test_rejection_is_not_connection_success(monkeypatch):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, text='Invalid API key')), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    result = await node({'operation':'list_customers'}).execute({})
    assert result == {'status':'error','http_status':401,'error':'Invalid API key'}

@pytest.mark.parametrize('identifier',['..','a/b','x?admin=true','x#fragment','x\\path'])
def test_path_injection_rejected(identifier):
    with pytest.raises(ConfigValidationError):
        node({'operation':'get_customer','customer_id':identifier})

def test_update_requires_actual_change_and_response_needs_answers():
    with pytest.raises(ConfigValidationError):
        node({'operation':'update_answer','answer_id':'1'})
    with pytest.raises(ConfigValidationError):
        node({'operation':'create_or_update_response','survey_id':1,'answers':[]})
