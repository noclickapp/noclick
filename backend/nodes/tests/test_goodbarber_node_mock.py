"""Exercise GoodBarber request mapping with the provider's published examples.

Covers token transport, write bodies, errors and new-order deduplication without
requiring a live shop or sending changes to the provider.
"""
import json
from pathlib import Path
from contextlib import asynccontextmanager
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes import goodbarber_node as gb

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/goodbarber/responses.json').read_text())
CREDENTIAL = {'credential_type': 'goodbarber_api_token', 'api_token': 'test-goodbarber-secret', 'webzine_id': 145245}

def node(config):
    return NodeFactory.create_node('goodbarber-test', 'automation-goodbarber', {'config': config, 'credentials': CREDENTIAL})

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(gb.OPERATIONS))
async def test_contract_route_and_example(operation, monkeypatch):
    spec = gb.OPERATIONS[operation]
    model = next(m for m in gb.GoodBarberConfig.__args__[0].__args__ if m.model_fields['operation'].default == operation)
    cfg = {'operation': operation}
    # Populate required fields from the pinned schema; optional fields remain omitted.
    for key, field in model.model_fields.items():
        if field.is_required():
            cfg[key] = [] if str(field.annotation).startswith('list[') else 'Color' if field.annotation is str else 123
    if operation == 'update_product': cfg['meta_description'] = 'newMETA DESC'
    if operation == 'update_option': cfg['name'] = 'Color'
    if operation == 'update_shipping': cfg['status'] = 'FULFILLED'
    expected = FIXTURES.get(operation)
    calls = []
    def handle(request):
        calls.append(request)
        assert request.headers['token'] == CREDENTIAL['api_token']
        assert request.url.host == 'commerce.goodbarber.dev'
        assert request.method == spec['method']
        assert request.url.path == spec['path'].format(webzine_id=145245, product_id=123, option_id=123, collection_id=123, customer_id=123, user_id=123, order_id=123)
        if spec['body']:
            body = json.loads(request.content)
            assert body == {k: v for k, v in cfg.items() if k in spec['body']}
        return httpx.Response(204) if operation.startswith('delete_') else httpx.Response(200, json=expected)
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c:
            yield c
    monkeypatch.setattr(gb, 'guarded_async_client', client)
    result = await node(cfg).execute({})
    assert result['data'] == expected
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_rejection_is_not_success(monkeypatch):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'error_code': 1999, 'error_description': 'AUTHENTICATION_FAILED'}))) as c:
            yield c
    monkeypatch.setattr(gb, 'guarded_async_client', client)
    with pytest.raises(ValueError, match='AUTHENTICATION_FAILED'):
        await node({'operation': 'list_products'}).execute({})

@pytest.mark.asyncio
async def test_poll_documented_orders_and_scope(monkeypatch):
    n = node({'operation': 'on_new_order', 'creation_date_from': '2021-01-25T13:10'})
    payload = FIXTURES['list_orders']
    pages = []
    async def request(method, path, **kwargs):
        pages.append(kwargs['params'])
        return {**payload, 'next': None}
    seen = set()
    async def unseen(rows, key):
        fresh = [row for row in rows if key(row) not in seen]
        seen.update(map(key, rows))
        return fresh
    monkeypatch.setattr(n, '_request', request)
    monkeypatch.setattr(n, '_filter_unseen', unseen)
    result = await n.execute({})
    assert result['new_order_count'] == 2
    assert 'Brian' in gb.GoodBarberNode.resolve_agent_event(result)['text']
    assert pages[0]['creation_date_from'] == '2021-01-25T13:10'
    assert gb.GoodBarberNode.should_propagate_output(result, {'operation': 'on_new_order'})
    result = await n.execute({})
    assert result['new_order_count'] == 0
    assert not gb.GoodBarberNode.should_propagate_output(result, {'operation': 'on_new_order'})
