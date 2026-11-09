"""Real factory requests against examples from the official OpenAPI contract."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import logo_dev_node as node
from nodes.core.registry import NodeFactory
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/logo-dev/responses.json').read_text())['responses']
AUTH = {'credential_type': 'logo_dev_api_key', 'api_key': 'sk_fixture_not_live'}
BRAND = 'brand_4x0wr3g0000g00400000000004'
ENDPOINT = 'ep_2mX9kL4pQ7rT1vW3yZ5aB8cD0e'
CASES = [
    ('get_brand', {'domain': 'stripe.com'}, 'GET /v2/brands', 200),
    ('get_brand_by_id', {'brand_id': BRAND}, 'GET /v2/brands/{id}', 200),
    ('get_brand_logo', {'domain': 'stripe.com'}, 'GET /v2/brands/logo', 200),
    ('get_brandmark', {'domain': 'stripe.com'}, 'GET /v2/brands/brandmark', 200),
    ('search_brands', {'q': 'sweetgreen'}, 'GET /v2/search', 200),
    ('get_subscription', {'brand_id': BRAND}, 'GET /v2/brands/{id}/subscription', 200),
    ('subscribe_brand', {'brand_id': BRAND}, 'PUT /v2/brands/{id}/subscription', 201),
    ('unsubscribe_brand', {'brand_id': BRAND}, 'DELETE /v2/brands/{id}/subscription', 204),
    ('create_webhook_endpoint', {'url': 'https://hooks.example.com/logo-dev', 'filter_types': ['brand.updated']}, 'POST /v2/webhook_endpoints', 201),
    ('list_webhook_endpoints', {}, 'GET /v2/webhook_endpoints', 200),
    ('get_webhook_endpoint', {'endpoint_id': ENDPOINT}, 'GET /v2/webhook_endpoints/{id}', 200),
    ('update_webhook_endpoint', {'endpoint_id': ENDPOINT, 'disabled': False, 'filter_types': []}, 'PATCH /v2/webhook_endpoints/{id}', 200),
    ('delete_webhook_endpoint', {'endpoint_id': ENDPOINT}, 'DELETE /v2/webhook_endpoints/{id}', 204),
    ('get_webhook_secret', {'endpoint_id': ENDPOINT}, 'GET /v2/webhook_endpoints/{id}/secret', 200),
    ('rotate_webhook_secret', {'endpoint_id': ENDPOINT}, 'POST /v2/webhook_endpoints/{id}/secret', 200),
    ('get_account', {}, 'GET /v2/account', 200),
    ('flag_domains', {'domains': ['https://www.acme.com', 'example.com'], 'reason': 'incorrect_logo'}, 'POST /v2/flag', 200),
]


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        assert request.url.host == 'api.logo.dev'
        assert request.headers['authorization'] == 'Bearer ' + AUTH['api_key']
        assert AUTH['api_key'] not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, content=b'') if code == 204 else httpx.Response(code, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, **arguments):
    instance = NodeFactory.create_node(node_id='logo-dev-test', node_type='automation-logo-dev', node_data={
        'config': {'operation': operation, **arguments}, 'credentials': AUTH,
    })
    return await instance.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,arguments,route,code', CASES)
async def test_logo_dev_contract_operations(wire, operation, arguments, route, code):
    requests, replies = wire
    body = EXAMPLES[route][str(code)]
    replies.append((code, body))
    result = await run(operation, **arguments)
    assert result['status'] == 'success' and result['http_status'] == code
    assert result['data'] == (body['data'] if body else None)
    assert len(requests) == 1 and not replies
    method, path = route.split(' ')
    assert requests[0].method == method
    assert requests[0].url.path == path.replace('{id}', BRAND if '/brands/' in path else ENDPOINT)
    if method in {'POST', 'PATCH'} and set(arguments) - {'endpoint_id'}:
        assert json.loads(requests[0].content) == {k:v for k,v in arguments.items() if k != 'endpoint_id'}
    if operation == 'search_brands':
        assert dict(requests[0].url.params) == {'q': 'sweetgreen', 'method': 'match', 'limit': '10'}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,arguments,route,code', CASES[:4])
async def test_logo_dev_indexing_stays_pending(wire, operation, arguments, route, code):
    wire[1].append((202, EXAMPLES[route]['202']))
    result = await run(operation, **arguments)
    assert result['status'] == 'pending'
    assert result['metadata']['pending']['retry_after_seconds'] == 30
    assert len(wire[0]) == 1


@pytest.mark.asyncio
async def test_logo_dev_subscription_idempotent_status_and_nosubscribe(wire):
    wire[1].append((200, EXAMPLES['PUT /v2/brands/{id}/subscription']['200']))
    assert (await run('subscribe_brand', brand_id=BRAND))['status'] == 'success'
    wire[1].append((200, EXAMPLES['GET /v2/brands']['200']))
    await run('get_brand', ticker='aapl', nosubscribe='true')
    assert dict(wire[0][-1].url.params) == {'ticker': 'aapl', 'nosubscribe': 'true'}


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body', [(401, {'error': {'message': 'Invalid API key'}}), (429, {'error': {'message': 'Rate limit exceeded'}}), (200, {'error': {'message': 'Rejected'}}), (200, {'data': {}}), (302, {})])
async def test_logo_dev_refusals_do_not_pass(wire, code, body):
    wire[1].append((code, body))
    with pytest.raises(ValueError):
        await run('get_account')
    assert len(wire[0]) == 1


@pytest.mark.asyncio
async def test_logo_dev_error_redacts_key(wire):
    wire[1].append((401, {'error': {'message': 'Invalid ' + AUTH['api_key']}}))
    with pytest.raises(ValueError) as error:
        await run('get_account')
    assert AUTH['api_key'] not in str(error.value)
    assert 'Invalid' in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,arguments', [
    ('get_brand', {}), ('get_brand', {'domain': 'stripe.com', 'name': 'Stripe'}),
    ('get_brand_by_id', {'brand_id': '../account'}),
    ('get_webhook_endpoint', {'endpoint_id': 'ep_x/secret'}),
    ('search_brands', {'q': 'stripe', 'limit': 26}),
    ('update_webhook_endpoint', {'endpoint_id': ENDPOINT}),
    ('create_webhook_endpoint', {'url': 'http://hooks.example.com'}),
    ('flag_domains', {'domains': [], 'reason': 'incorrect_logo'}),
    ('flag_domains', {'domains': ['stripe.com'], 'reason': 'made_up'}),
])
async def test_logo_dev_invalid_input_makes_no_request(wire, operation, arguments):
    with pytest.raises(ValueError):
        await run(operation, **arguments)
    assert wire[0] == []


def test_logo_dev_manual_credential_default():
    assert node.LogoDevCredential(api_key=AUTH['api_key']).credential_type == 'logo_dev_api_key'
    with pytest.raises(ValidationError):
        node.LogoDevCredential(api_key='Bearer sk_example')
