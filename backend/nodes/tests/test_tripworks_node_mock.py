"""HTTP-boundary tests with request and entity examples from the pinned TripWorks OpenAPI 1.1.6."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes import tripworks_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures' / 'tripworks'
CASES = json.loads((FIXTURES / 'request_examples.json').read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='tripworks-test', node_type='automation-tripworks', node_data={
        'config': config, 'credentials': {'credential_type': 'tripworks_api_key', 'account': 'demo', 'api_key': 'tw_test_fixture'}})

def transport(monkeypatch, handler):
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)

@pytest.mark.asyncio
@pytest.mark.parametrize('name', CASES)
async def test_requests_use_documented_methods_and_paths(monkeypatch, name):
    case = CASES[name]
    requests = []
    def reply(request):
        requests.append(request)
        assert request.method == case['method']
        assert request.url.host == 'demo.tripworks.com'
        assert request.url.path == case['path']
        assert request.headers['Authorization'] == 'Bearer tw_test_fixture'
        if case['method'] != 'GET':
            body = json.loads(request.content)
            for key, value in case['config'].items():
                if key not in {'operation', 'id'}:
                    assert body[key] == value
        if name == 'set_booking_status':
            assert json.loads(request.content)['decisions'] == {}
        return httpx.Response(200, json={'success': True})
    transport(monkeypatch, reply)
    assert (await node(case['config']).execute({}))['status'] == 'success'
    assert len(requests) == 1

@pytest.mark.asyncio
async def test_email_and_cursor_encoding(monkeypatch):
    def reply(request):
        assert request.url.params['email[eq]'] == 'jane+vip@example.com'
        assert request.url.params['cursor'] == 'opaque/+=cursor'
        return httpx.Response(200, json={'success': True, 'customers': [], 'meta': {'has_more': False}})
    transport(monkeypatch, reply)
    await node({'operation':'list_customers','email':'jane+vip@example.com','cursor':'opaque/+=cursor'}).execute({})

@pytest.mark.asyncio
@pytest.mark.parametrize('resource', ['customers','trips'])
async def test_poll_documented_entities_paginate_before_dedup(monkeypatch, resource):
    payload = json.loads((FIXTURES / (resource+'.json')).read_text())
    calls = []
    def reply(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={**payload, 'meta': {'has_more':True,'next_cursor':'next'}})
        assert request.url.params['cursor'] == 'next'
        return httpx.Response(200, json={**payload, resource:[]})
    transport(monkeypatch, reply)
    n = node({'operation':'on_new_'+resource})
    dedup = AsyncMock(return_value=payload[resource])
    monkeypatch.setattr(n, '_filter_unseen', dedup)
    result = await n.execute({})
    assert result['new_item_count'] == 1
    items, key = dedup.call_args.args
    assert key(items[0]) == str(payload[resource][0]['id'])
    assert native.TripWorksNode.should_propagate_output(result, {'operation':'on_new_'+resource})
    assert not native.TripWorksNode.should_propagate_output({'new_item_count':0}, {'operation':'on_new_'+resource})

@pytest.mark.asyncio
async def test_poll_repeated_cursor_does_not_consume_state(monkeypatch):
    payload = json.loads((FIXTURES/'customers.json').read_text())
    transport(monkeypatch, lambda _: httpx.Response(200,json={**payload,'meta':{'has_more':True,'next_cursor':'same'}}))
    n=node({'operation':'on_new_customers'})
    dedup=AsyncMock()
    monkeypatch.setattr(n,'_filter_unseen',dedup)
    with pytest.raises(ValueError, match='pagination'):
        await n.execute({})
    dedup.assert_not_called()

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401,403,409,422,429,500])
async def test_errors_never_become_success(monkeypatch,status):
    transport(monkeypatch, lambda _: httpx.Response(status,json={'success':False,'message':'Provider rejected request'}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation':'list_customers'}).execute({})

@pytest.mark.parametrize('account',['https://demo.tripworks.com','evil.example','demo/elsewhere','demo@evil','127.0.0.1','-bad'])
def test_account_boundary(account):
    with pytest.raises(ValidationError):
        native.TripWorksCredential(account=account,api_key='tw_fixture')
