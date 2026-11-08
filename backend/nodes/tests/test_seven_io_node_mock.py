"""Verify Seven's wire requests and documented response envelopes without sending messages.

These tests keep credentials in headers, preserve form fields and surface provider failures.
"""
from contextlib import asynccontextmanager
from urllib.parse import parse_qs
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes import seven_io_node as seven


CASES = [
    ('get_balance', {}, 'GET', '/balance', {'amount': 12.34, 'currency': 'EUR'}),
    ('list_contacts', {}, 'GET', '/contacts', {'data': [], 'pagingMetadata': {}}),
    ('get_contact', {'id': 123}, 'GET', '/contacts/123', {'id': 123}),
    ('create_contact', {'firstname': 'Jane', 'mobile_number': '4917612345678'}, 'POST', '/contacts', {'id': 123}),
    ('update_contact', {'id': 123, 'lastname': 'Doe'}, 'PATCH', '/contacts/123', {'id': 123}),
    ('delete_contact', {'id': 123}, 'DELETE', '/contacts/123', {'success': True}),
    ('list_groups', {}, 'GET', '/groups', {'data': []}),
    ('get_group', {'id': 123}, 'GET', '/groups/123', {'id': 123, 'name': 'Customers'}),
    ('create_group', {'name': 'Customers'}, 'POST', '/groups', {'id': 123}),
    ('update_group', {'id': 123, 'name': 'Customers'}, 'PATCH', '/groups/123', {'id': 123}),
    ('delete_group', {'id': 123}, 'DELETE', '/groups/123', {'success': True}),
    ('send_sms', {'to': '4917612345678', 'text': 'Hello World', 'sender': 'Shop'}, 'POST', '/sms', {'success': '100', 'messages': []}),
    ('get_sms_status', {'msg_id': '77231715575'}, 'GET', '/status', []),
    ('list_outbound_messages', {'offset': 100}, 'GET', '/journal/outbound', []),
    ('list_inbound_messages', {}, 'GET', '/journal/inbound', []),
    ('lookup_format', {'number': '4917612345678'}, 'GET', '/lookup/format', {'success': True, 'international': '+4917612345678'}),
    ('lookup_hlr', {'number': '4917612345678'}, 'GET', '/lookup/hlr', {'status': True, 'lookup_outcome': True}),
    ('get_analytics_by_date', {'start': '2026-01-01'}, 'GET', '/analytics/date', []),
]


def make_node(op, config):
    return NodeFactory.create_node(node_id='seven-test', node_type='automation-seven-io', node_data={
        'config': {'operation': op, **config},
        'credentials': {'credential_type': 'seven_io_api_key', 'api_key': 'test-secret'},
    })


@pytest.mark.asyncio
@pytest.mark.parametrize('op,config,method,path,body', CASES)
async def test_wire(monkeypatch, op, config, method, path, body):
    def handler(req):
        assert req.method == method
        assert req.url.path == '/api' + path
        assert req.headers['X-Api-Key'] == 'test-secret'
        assert 'test-secret' not in str(req.url)
        values = dict(req.url.params) if method == 'GET' else {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        for k, v in config.items():
            if k != 'id':
                assert values['from' if k == 'sender' else k] == str(v)
        if op == 'delete_group':
            assert values['delete_contacts'] == 'false'  # never cascade implicitly
        return httpx.Response(200, json=body)
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c
    monkeypatch.setattr(seven, 'guarded_async_client', client)
    result = await make_node(op, config).execute({})
    assert result == {'status': 'success', 'data': body}


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(200, {'success': False, 'error': 'Rejected'}), (200, {'success': '900'})])
async def test_error_envelopes(monkeypatch, status, body):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body))) as c:
            yield c
    monkeypatch.setattr(seven, 'guarded_async_client', client)
    assert (await make_node('send_sms', {'to': '4917612345678', 'text': 'Hello'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_documented_contact(monkeypatch):
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / 'fixtures/seven-io/documented_responses.json').read_text())
    body = fixture['GET /contacts/{id}']['body']
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body))) as c:
            yield c
    monkeypatch.setattr(seven, 'guarded_async_client', client)
    assert (await make_node('get_contact', {'id': body['id']}).execute({}))['data'] == body


@pytest.mark.asyncio
async def test_empty_delete(monkeypatch):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b''))) as c:
            yield c
    monkeypatch.setattr(seven, 'guarded_async_client', client)
    assert (await make_node('delete_contact', {'id': 123}).execute({}))['status'] == 'success'


@pytest.mark.asyncio
async def test_rejected_key(monkeypatch):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(401, json={'error': 'Invalid API key'}))) as c:
            yield c
    monkeypatch.setattr(seven, 'guarded_async_client', client)
    with pytest.raises(httpx.HTTPStatusError):
        await make_node('list_contacts', {}).execute({})
