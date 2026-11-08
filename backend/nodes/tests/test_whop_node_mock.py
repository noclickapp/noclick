"""Exercise Whop request construction and response handling without credentials."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import whop_node as whop
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/whop/operations.json').read_text())

@pytest.fixture
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='whop-test', node_type='automation-whop', node_data={
        'config': config, 'credentials': {'credential_type': 'whop_api_key', 'api_key': 'test-realistic-key'}})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_requests(monkeypatch, operation):
    config = CASES[operation]
    requests = []
    def answer(request):
        requests.append(request)
        assert request.url.host == 'api.whop.com'
        assert request.headers['Authorization'] == 'Bearer test-realistic-key'
        assert request.headers['Api-Version-Date'] == '2026-11-07'
        assert 'test-realistic-key' not in str(request.url) + request.content.decode()
        resource = {'id': config.get('id', 'biz_example'), 'title': 'Whop test account'}
        return httpx.Response(200, json={'data': [resource], 'page_info': {'end_cursor': 'cursor2', 'has_next_page': True}} if operation.startswith('list_') else resource)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as c:
            yield c
    monkeypatch.setattr(whop, 'guarded_async_client', client)
    n = node(config); n.emit = AsyncMock()
    output = await n.execute({})
    assert output['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    # Explicit public resource names, independent of the implementation route table.
    resource = 'accounts/me' if operation == 'get_account' else 'promo_codes' if 'promo_code' in operation else 'memberships' if 'membership' in operation else 'refunds' if operation in {'list_refunds','get_refund'} else 'payments' if 'payment' in operation else 'products'
    suffix = '/' + config['id'] if 'id' in config else ''
    if operation in {'publish_product','unpublish_product','cancel_membership','refund_payment','activate_promo_code','deactivate_promo_code'}:
        suffix += '/' + operation.split('_')[0]
    assert request.url.path == '/api/v1/' + resource + suffix
    method = 'POST' if operation.split('_')[0] in {'create','publish','unpublish','cancel','refund','activate','deactivate'} else 'PATCH' if operation.startswith('update') else 'DELETE' if operation.startswith('delete') else 'GET'
    assert request.method == method
    fields = {k:v for k,v in config.items() if k not in {'operation','id'}}
    if method == 'GET':
        assert dict(request.url.params) == {k:str(v) for k,v in fields.items()}
        assert request.content == b''
    elif method != 'DELETE':
        assert json.loads(request.content) == fields
    if operation.startswith('list_'):
        assert output['data']['page_info']['end_cursor'] == 'cursor2'
    else:
        assert output['data']['id'] == config.get('id', 'biz_example')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401,403,429,500,302])
async def test_rejection_is_not_success_or_retried(monkeypatch,status):
    count=0
    def answer(request):
        nonlocal count
        count+=1
        return httpx.Response(status, text='provider rejection test-realistic-key')
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as c:yield c
    monkeypatch.setattr(whop,'guarded_async_client',client)
    with pytest.raises(ValueError,match=f'Whop HTTP {status}: provider rejection \\[redacted\\]'):
        await node({'operation':'get_account'}).execute({})
    assert count==1


def test_resource_injection_and_empty_update_refused():
    for config in [{'operation':'get_product','id':'../accounts/me'}, {'operation':'update_membership','id':'mem_example'}]:
        with pytest.raises(ValueError):node(config)


@pytest.mark.asyncio
async def test_cursor_is_sent_without_following_it_as_url(monkeypatch):
    @asynccontextmanager
    async def client(**kwargs):
        def answer(request):
            assert request.url.host=='api.whop.com'
            assert request.url.params['after']=='https://untrusted.example/cursor'
            return httpx.Response(200,json={'data':[],'page_info':{'has_next_page':False}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as c:yield c
    monkeypatch.setattr(whop,'guarded_async_client',client)
    await node({'operation':'list_payments','first':25,'after':'https://untrusted.example/cursor'}).execute({})


@pytest.mark.parametrize('token', ['', '   ', 'Bearer sample', 'key\nvalue'])
def test_invalid_key_format(token):
    with pytest.raises(ValueError):
        whop.WhopAPIKeyCredential(api_key=token)
