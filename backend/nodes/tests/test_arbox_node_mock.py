"""Exercise Arbox via the real node factory with intercepted HTTP only."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import arbox_node as arbox
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURES = Path(__file__).parent / 'fixtures' / 'arbox'
CASES = json.loads((FIXTURES / 'operations.json').read_text())
LOCATIONS = json.loads((FIXTURES / 'locations.json').read_text())
AUTH = {'credential_type': 'arbox_api_key', 'api_key': 'arbox-fixture-key'}
USER = '00000000-0000-4000-8000-000000000001'


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))

    async def send(request):
        requests.append(request)
        assert request.url.host == 'arboxserver.arboxapp.com'
        assert request.headers['api-key'] == AUTH['api_key']
        assert AUTH['api_key'] not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        code, payload = reply
        if isinstance(payload, bytes):
            return httpx.Response(code, content=payload, headers={'Content-Type': 'text/html'})
        return httpx.Response(code, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(arbox, 'guarded_async_client', lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, args=None, auth=AUTH):
    return await run_node_operation(node_type='automation-arbox', operation=operation,
        arguments=args or {}, credential_data=auth, user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_arbox_all_operations_exact_wire(transport, case):
    requests, replies = transport
    replies.append((200, LOCATIONS))
    result = await run(case['operation'], case['arguments'])
    assert result['success'] is True and result['data'] == LOCATIONS['data']
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == case['method']
    assert request.url.path == case['path']
    assert dict(request.url.params) == {k: str(v) for k, v in case['query'].items()}
    assert (json.loads(request.content) if request.content else None) == case['body']
    if request.method != 'GET':
        assert result['write_outcome'] == 'acknowledged'


@pytest.mark.asyncio
async def test_arbox_pagination_filters_and_no_completion_claim(transport):
    requests, replies = transport
    replies.append((200, {'statusCode': 200, 'data': [], 'extra': []}))
    result = await run('list_users', {'page': 4, 'limit': 50, 'location_id': 12, 'active': '0', 'only_clients': '1', 'sort': 'desc'})
    assert dict(requests[0].url.params) == {'page': '4', 'limit': '50', 'location_id': '12', 'active': '0', 'only_clients': '1', 'sort': 'desc'}
    assert result['pagination'] == {'page': 4, 'limit': 50, 'next_page_to_try': 5, 'completion_known': False}


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body', [
    (401, {'message': 'Invalid API key'}), (422, {'message': 'Invalid location'}),
    (429, {'message': 'Too many requests'}), (500, {'message': 'Unavailable'}),
    (302, b'<html>Redirect</html>'), (200, b'<html>Sign in</html>'),
    (200, {'statusCode': 401, 'message': 'Invalid API key'}),
    (200, {'error': 'denied'}), (200, {'data': {}}), (200, ['unexpected']),
])
async def test_arbox_rejects_errors_and_unexpected_responses(transport, code, body):
    requests, replies = transport
    replies.append((code, body))
    result = await run('list_locations')
    assert result['success'] is False and result['error']
    assert len(requests) == 1
    if code == 401:
        assert result['error'] == 'Invalid API key'


@pytest.mark.asyncio
async def test_arbox_write_timeout_not_retried_or_claimed_complete(transport):
    requests, replies = transport
    replies.append(httpx.ReadTimeout('private request detail'))
    result = await run('create_user', {'first_name': 'Jane', 'last_name': 'Smith'})
    assert result['success'] is False and result['write_outcome'] == 'unverified'
    assert len(requests) == 1 and 'private request detail' not in str(result)


@pytest.mark.asyncio
async def test_arbox_response_does_not_leak_credential(transport):
    _, replies = transport
    replies.append((200, {'statusCode': 200, 'data': [{'note': AUTH['api_key'], 'api_key': AUTH['api_key']}]}))
    assert AUTH['api_key'] not in json.dumps(await run('list_locations'))


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,args', [
    ('get_user', {'user_id': '../archive'}), ('get_user', {'user_id': 0}),
    ('complete_task', {'task_id': '1/../../users'}), ('list_users', {'limit': 501}),
    ('list_users', {'page': 0}), ('list_users', {'sort': 'wrong'}),
    ('list_tasks', {'from_date': '2026-11-30', 'to_date': '2026-11-01'}),
    ('create_lead', {'first_name': 'Jane', 'location_id': 1}),
    ('update_user', {'user_id': 1}), ('search_users', {'type': 'bad', 'value': 'x'}),
])
async def test_arbox_bad_input_before_http(transport, operation, args):
    with pytest.raises(ValueError):
        await run(operation, args)
    assert not transport[0]


@pytest.mark.parametrize('key', ['https://example.com/key', 'a\nb', 'Bearer token', '{{ key }}'])
def test_arbox_manual_key_shaping(key):
    with pytest.raises((ValueError, ValidationError)):
        arbox.ArboxAPIKeyCredential(api_key=key)


def test_arbox_manual_type_default_and_evidence():
    assert arbox.ArboxAPIKeyCredential(api_key='  arbox-fixture-key  ').credential_type == 'arbox_api_key'
    assert arbox.ArboxNode.connection_evidence.operation == 'list_locations'
    assert arbox.ArboxNode.connection_evidence.label_keys[0] == 'location_name'
