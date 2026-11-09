"""Exercise Tentary's real node using request and response examples from its v1 contract.

The HTTP transport is replaced locally; no provider credential or account is used.
"""
import json
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from nodes import tentary_node as native
from nodes.core.registry import NodeFactory
from nodes.core.base import ConfigValidationError

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/tentary/examples.json').read_text())
KEY = 'tnt_synthetic_tentary_test_key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='tentary-test', node_type='automation-tentary',
        node_data={'config': config, 'credentials': credentials or {'credential_type': 'tentary_api_key', 'api_key': KEY}})


def transport(monkeypatch, payload, status=200, headers=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=payload, headers=headers)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_tentary_documented_examples(operation, monkeypatch):
    example = EXAMPLES[operation]
    requests = transport(monkeypatch, example['response'])
    output = await node(example['config']).execute({})
    assert output == {'status': 'success', 'data': example['response']}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example['method']
    path = example['path']
    for name, value in example['config'].items():
        path = path.replace('{' + name + '}', str(value))
    assert request.url.host == 'api.tentary.com' and request.url.path == path
    assert request.headers['Authorization'] == 'Bearer ' + KEY
    if example['method'] in {'POST', 'PATCH'}:
        expected = dict(example['body'])
        if 'price' in expected:
            expected['price'] = str(expected['price'])
        assert json.loads(request.content) == expected
    else:
        assert not request.content
    assert KEY not in str(output)


@pytest.mark.asyncio
async def test_tentary_cursor_filters_dates_and_false(monkeypatch):
    response = {'items': [], 'next_cursor': 'cursor-2'}
    requests = transport(monkeypatch, response)
    output = await node({'operation': 'search_customers', 'query': 'Anna + café',
                         'paid_only': False, 'cursor': 'cursor-1', 'limit': 2}).execute({})
    assert dict(requests[0].url.params) == {'query': 'Anna + café', 'paid_only': 'false', 'cursor': 'cursor-1', 'limit': '2'}
    assert output['data']['next_cursor'] == 'cursor-2' and len(requests) == 1
    requests = transport(monkeypatch, EXAMPLES['list_orders']['response'])
    await node({'operation': 'list_orders', 'from_date': '2026-01-01', 'to_date': '2026-10-29'}).execute({})
    assert dict(requests[0].url.params) == {'from': '2026-01-01', 'to': '2026-10-29'}


@pytest.mark.asyncio
async def test_tentary_patch_explicit_null_and_false_survive_omission(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES['update_coupon']['response'])
    await node({'operation': 'update_coupon', 'coupon_id': 702, 'ends_on': None, 'product_ids': []}).execute({})
    assert json.loads(requests[0].content) == {'ends_on': None, 'product_ids': []}
    requests = transport(monkeypatch, EXAMPLES['update_course']['response'])
    await node({'operation': 'update_course', 'course_id': 202, 'tracks_progress': False}).execute({})
    assert json.loads(requests[0].content) == {'tracks_progress': False}


@pytest.mark.asyncio
async def test_tentary_access_email_and_revoke_semantics(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES['grant_access']['response'])
    await node({'operation': 'grant_access', 'email': 'lisa.hahn@example.com', 'product_id': 101, 'send_email': False}).execute({})
    assert json.loads(requests[0].content) == {'email': 'lisa.hahn@example.com', 'product_id': 101, 'send_email': False}
    requests = transport(monkeypatch, EXAMPLES['revoke_access']['response'])
    result = await node({'operation': 'revoke_access', 'email': 'jonas.wolf@example.com', 'product_id': 101, 'variant_id': 0}).execute({})
    assert json.loads(requests[0].content)['variant_id'] == 0
    assert result['data']['status'] == 'revoked'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404, 422, 429, 500])
async def test_tentary_provider_rejection_no_retry_and_secret_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {'error': {'message': 'Key refused: ' + KEY}}, status)
    result = await node({'operation': 'get_account_overview'}).execute({})
    assert result == {'status': 'error', 'status_code': status, 'error': 'Key refused: [redacted]'}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_tentary_refuses_redirect_and_non_object(monkeypatch):
    requests = transport(monkeypatch, {}, 302, {'location': 'https://example.com'})
    result = await node({'operation': 'get_account_overview'}).execute({})
    assert result['status'] == 'error' and len(requests) == 1
    transport(monkeypatch, [])
    with pytest.raises(ValueError, match='unexpected response shape'):
        await node({'operation': 'get_account_overview'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_product', 'product_id': '../orders'},
    {'operation': 'get_product', 'product_id': 0},
    {'operation': 'list_products', 'limit': 51},
    {'operation': 'list_products', 'type': 'other'},
    {'operation': 'create_coupon', 'code': 'RUNNER15'},
    {'operation': 'create_coupon', 'code': 'RUNNER15', 'percent': 15, 'amount': '10.00'},
    {'operation': 'create_coupon', 'code': 'RUNNER15', 'amount': '0.00'},
    {'operation': 'list_orders', 'from_date': '2026-02-30'},
    {'operation': 'list_orders', 'from_date': '2026-10-30', 'to_date': '2026-10-29'},
])
def test_tentary_invalid_inputs_fail_before_network(config):
    with pytest.raises(ConfigValidationError):
        native.TentaryNode.parse_config({'config': config})


def test_tentary_manual_key_default_and_evidence():
    assert native.TentaryAPIKeyCredential(api_key=KEY).credential_type == 'tentary_api_key'
    assert native.TentaryNode.connection_evidence.operation is None
    assert native.TentaryNode.connection_evidence.identity_operation == 'get_account_overview'
    with pytest.raises(ValidationError):
        native.TentaryAPIKeyCredential(api_key='Bearer ' + KEY)


@pytest.mark.asyncio
async def test_tentary_connect_evidence_names_shop_and_preserves_rejection(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    import nodes.core.run_op as runner
    async def run_operation(**kwargs):
        return await node({'operation': kwargs['operation']}, kwargs['credential_data']).execute({})
    monkeypatch.setattr(runner, 'run_node_operation', run_operation)
    transport(monkeypatch, EXAMPLES['get_account_overview']['response'])
    kwargs = dict(node_type='automation-tentary', user_id='test-user', pool=None,
                  credential_data={'credential_type': 'tentary_api_key', 'api_key': KEY})
    result = await collect_evidence(**kwargs)
    assert result.reachable is True and result.account_label == 'Lena Berg Yoga'
    transport(monkeypatch, {'message': 'This key was revoked.'}, 401)
    result = await collect_evidence(**kwargs)
    assert result.reachable is False and 'This key was revoked.' in result.error
