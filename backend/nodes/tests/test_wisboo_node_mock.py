"""Wire-contract and poll regressions using Wisboo's published response examples."""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import wisboo_node as native
from nodes.core.poll_trigger import poll_scope

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/wisboo/documented_responses.json').read_text())
CREDENTIAL = {'credential_type': 'wisboo_api_key', 'api_key': 'test-wisboo-secret-42', 'store_id': 'store123'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return native.WisbooNode(node_id='wisboo-test', node_type='automation-wisboo',
        node_data={'config': config}, sio=Mock(),
        config=native.WisbooNodeConfig.model_validate({'config': config, 'credentials': credential or CREDENTIAL}))


def transport(monkeypatch, reply, status=200):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        if callable(reply):
            return reply(request)
        return httpx.Response(status, json=reply) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


# Explicit expectations deliberately independent of the node's route table.
CASES = [
    ('list_users', {}, 'GET', '/users', None, 'users-list-users', 200),
    ('create_user', {'name': 'John', 'last_name': 'Doe', 'email': 'john_doe@example.com', 'language': 'ES'}, 'POST', '/users', {'name': 'John', 'last_name': 'Doe', 'email': 'john_doe@example.com', 'language': 'ES'}, 'users-create-user', 201),
    ('get_user', {'user_id': 'id'}, 'GET', '/users/id', None, 'users-get-user', 200),
    ('update_user', {'user_id': 'id', 'name': 'John'}, 'PUT', '/users/id', {'name': 'John'}, 'users-update-user', 200),
    ('update_user_email', {'user_id': 'id', 'email': 'new_email@example.com'}, 'PUT', '/users/id/email', {'email': 'new_email@example.com'}, 'users-update-user-email', 200),
    ('generate_magic_link', {'user_id': 'id'}, 'POST', '/users/id/magic_links', None, 'users-generate-magic-link', 201),
    ('list_purchases', {}, 'GET', '/purchases', None, 'purchases-list-purchases', 200),
    ('list_product_accesses', {'product_id': 'product-one', 'user_id': 'user-one'}, 'GET', '/product_accesses', None, 'product-access-list-product-accesses', 200),
    ('grant_product_access', {'user_id': 'user-one', 'product_id': 'product-one'}, 'POST', '/product_accesses', {'user_id': 'user-one', 'product_id': 'product-one'}, 'product-access-grant-product-access', 201),
    ('update_product_access', {'access_id': 'id', 'status': 'without_access', 'access_due_date': '2024-01-15T09:30:00Z'}, 'PUT', '/product_accesses/id', {'status': 'without_access', 'access_due_date': '2024-01-15T09:30:00Z'}, 'product-access-update-product-access', 201),
    ('revoke_product_access', {'access_id': 'id'}, 'DELETE', '/product_accesses/id', {}, None, 204),
    ('list_products', {}, 'GET', '/products', None, 'products-list-products', 200),
    ('get_product', {'product_id': 'id'}, 'GET', '/products/id', None, 'products-get-product', 200),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,body,example,status', CASES)
async def test_documented_operations(monkeypatch, operation, config, method, path, body, example, status):
    payload = EXAMPLES[example]['body'] if example else None
    calls = transport(monkeypatch, payload, status)
    result = await node({'operation': operation, **config}).execute({})
    assert result['status'] == 'success'
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.path == '/v1/stores/store123' + path
    assert request.headers['Authorization'] == 'Bearer test-wisboo-secret-42'
    assert (json.loads(request.content) if request.content else None) == body
    if operation.startswith('list_'):
        assert dict(request.url.params) == {'page': '1', 'size': '50', **({'product_id[]': 'product-one', 'user_id[]': 'user-one'} if operation == 'list_product_accesses' else {})}
        assert result['data'] == payload['data']
        assert result['metadata'] == payload['metadata']
    else:
        assert result['data'] == payload


@pytest.mark.asyncio
async def test_email_update_accepts_documented_empty_200(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200))
    result = await node({'operation': 'update_user_email', 'user_id': 'id', 'email': 'new_email@example.com'}).execute({})
    assert result['data'] is None and result['http_status'] == 200


@pytest.mark.asyncio
async def test_idempotency_and_path_encoding(monkeypatch):
    calls = transport(monkeypatch, EXAMPLES['users-update-user']['body'])
    await node({'operation': 'update_user', 'user_id': 'id/with?special', 'name': 'John', 'idempotency_key': 'request-42'}).execute({})
    assert calls[0].url.raw_path == b'/v1/stores/store123/users/id%2Fwith%3Fspecial'
    assert calls[0].headers['X-Idempotency-Key'] == 'request-42'
    assert json.loads(calls[0].content) == {'name': 'John'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404, 422, 429, 500])
async def test_rejections_redact_key_and_never_retry(monkeypatch, status):
    calls = transport(monkeypatch, {'message': 'rejected ' + CREDENTIAL['api_key']}, status)
    with pytest.raises(ValueError, match=f'Wisboo HTTP {status}') as exc:
        await node({'operation': 'list_products'}).execute({})
    assert CREDENTIAL['api_key'] not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [None, [], {'data': {}}, {'data': [None]}])
async def test_invalid_lists_fail(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({'operation': 'list_products'}).execute({})


def test_manual_connect_and_validation():
    credential = native.WisbooAPIKeyCredential.model_validate({'api_key': 'real-shaped-test-key', 'store_id': 'store123'})
    assert credential.credential_type == 'wisboo_api_key'
    for key in ['https://example.com/key', 'Bearer key', 'key\r\nInjected: value']:
        with pytest.raises(ValidationError):
            native.WisbooAPIKeyCredential.model_validate({'api_key': key, 'store_id': 'store123'})
    with pytest.raises(ValidationError):
        node({'operation': 'create_user', 'name': 'John', 'email': 'john@example.com'})
    with pytest.raises(ValidationError):
        node({'operation': 'update_product_access', 'access_id': 'id', 'access_due_date': '2024-01-15T09:30:00'})


@pytest.mark.asyncio
async def test_poll_documented_payload_baseline_emit_dedup_and_agent(monkeypatch):
    payload = EXAMPLES['product-access-list-product-accesses']['body']
    calls = transport(monkeypatch, payload)
    watched = node({'operation': 'on_new_product_access', 'user_id': 'user-one', 'product_id': 'product-one'})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    watched._update_node_state = update
    baseline = await watched.execute({})
    assert baseline['new_access_count'] == 0
    state['seen_ids'] = []
    output = await watched.execute({})
    assert output['accesses'] == payload['data']
    assert output['new_access_count'] == 1
    event = native.WisbooNode.resolve_agent_event(output)
    assert 'Wisboo' in event['text']
    assert 'gained access' in event['text']
    assert 'product string; access string' in event['text']
    assert native.WisbooNode.should_propagate_output(output, {'operation': 'on_new_product_access'})
    repeated = await watched.execute({})
    assert repeated['new_access_count'] == 0
    assert native.WisbooNode.resolve_agent_event(repeated) is None
    assert not native.WisbooNode.should_propagate_output(repeated, {'operation': 'on_new_product_access'})
    assert dict(calls[0].url.params) == {'page': '1', 'size': '50', 'user_id[]': 'user-one', 'product_id[]': 'product-one'}


def test_poll_scope_uses_only_declared_filters():
    config = {'operation': 'on_new_product_access', 'user_id': 'user-one'}
    assert poll_scope(native.WisbooNode, config) == poll_scope(native.WisbooNode, {**config, 'label': 'cosmetic change'})
    assert poll_scope(native.WisbooNode, config) != poll_scope(native.WisbooNode, {**config, 'user_id': 'other-user'})


@pytest.mark.asyncio
async def test_incomplete_poll_does_not_update_seen_state(monkeypatch):
    transport(monkeypatch, {'data': [{'id': 'access-one'}], 'metadata': {'total_record_count': 51}})
    watched = node({'operation': 'on_new_product_access'})
    async def fail(*args, **kwargs):
        pytest.fail('An incomplete poll must not consume new accesses')
    watched._filter_unseen = fail
    with pytest.raises(ValueError, match='incomplete access page'):
        await watched.execute({})
