"""Exercise the native node against Kiwify's own published response examples."""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import kiwify_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/kiwify/responses.json').read_text())['operations']
TOKEN = 'synthetic-kiwify-access-token'
CREDENTIAL = {'credential_type': 'kiwify_access_token', 'access_token': TOKEN, 'account_id': 'XvS0qfkdzCZTg8z'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config, credential=None):
    node = NodeFactory.create_node(node_id='kiwify-fixture', node_type='automation-kiwify',
        node_data={'config': config, 'credentials': CREDENTIAL if credential is None else credential})
    node.emit = AsyncMock()
    return node


def mock_client(monkeypatch, response):
    seen = []
    def respond(request):
        seen.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_published_contract_examples_and_exact_requests(monkeypatch, operation):
    case = FIXTURES[operation]
    response = httpx.Response(case['http_status'], json=case['body']) if case['body'] is not None else httpx.Response(204)
    seen = mock_client(monkeypatch, response)
    node = make_node(case['config'])
    result = await node.execute({})
    assert NODE_REGISTRY['automation-kiwify'] is native.KiwifyNode
    assert result['status'] == 'success'
    assert result['http_status'] == case['http_status']
    assert len(seen) == 1
    req = seen[0]
    assert req.url.host == 'public-api.kiwify.com'
    assert req.url.path == case['path'] and req.method == case['method']
    assert req.headers['authorization'] == 'Bearer ' + TOKEN
    assert req.headers['x-kiwify-account-id'] == CREDENTIAL['account_id']
    assert {key: req.url.params.get_list(key) for key in req.url.params} == case['query']
    assert (json.loads(req.content) if req.content else None) == case['request_body']
    if case['body'] is not None:
        # The response envelope, provider status and participant nesting survive.
        expected = copy.deepcopy(case['body'])
        def remove_tokens(value):
            if isinstance(value, dict):
                return {k: remove_tokens(v) for k, v in value.items() if k != 'token'}
            if isinstance(value, list):
                return [remove_tokens(v) for v in value]
            return value
        assert result['data'] == remove_tokens(expected)
    else:
        assert result['deleted_id'] == case['config']['webhook_id']
    assert TOKEN not in str(result)
    node.emit.assert_awaited_once_with(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 404, 429, 500])
async def test_rejection_preserves_provider_message_without_secret(monkeypatch, status):
    seen = mock_client(monkeypatch, httpx.Response(status, json={'error': 'auth_error', 'message': 'Invalid token: ' + TOKEN}))
    result = await make_node({'operation': 'get_account_details'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'message': 'Invalid token: [redacted]'}
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_network_failure_does_not_retry_write(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout('timeout ' + TOKEN, request=request)
    seen = mock_client(monkeypatch, fail)
    with pytest.raises(ValueError, match='inspect the account'):
        await make_node(FIXTURES['refund_sale']['config']).execute({})
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(302, headers={'location': 'https://other.example/'}), httpx.Response(200, text='<html>wrong</html>'), httpx.Response(200, json=['unexpected'])])
async def test_bad_responses_and_redirects_cannot_report_success(monkeypatch, response):
    seen = mock_client(monkeypatch, response)
    try:
        result = await make_node({'operation': 'get_account_details'}).execute({})
    except ValueError:
        pass
    else:
        assert result['status'] == 'error'
    assert len(seen) == 1


@pytest.mark.parametrize('config', [
    {'operation': 'list_sales', 'start_date': '2026-01-01', 'end_date': '2026-06-01'},
    {'operation': 'list_sales', 'start_date': 'bad', 'end_date': '2026-01-01'},
    {'operation': 'list_sales', 'start_date': '2026-01-01'},
    {'operation': 'list_scheduled_installments', 'created_start': '2026-01-01'},
    {'operation': 'list_products', 'page_size': 101},
])
def test_invalid_required_inputs(config):
    with pytest.raises(ValueError):
        make_node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize('identifier', ['../sales', '..', 'x?override=y', 'x#fragment', 'x\\y'])
async def test_resource_path_injection_makes_no_request(monkeypatch, identifier):
    seen = mock_client(monkeypatch, httpx.Response(200, json={}))
    with pytest.raises(ValueError, match='resource ID'):
        await make_node({'operation': 'get_product', 'product_id': identifier}).execute({})
    assert not seen


def test_manual_credential_has_default_type_and_human_fields():
    parsed = native.KiwifyTokenCredential.model_validate({'access_token': ' '+TOKEN+' ', 'account_id': ' XvS0qfkdzCZTg8z '})
    assert parsed.credential_type == 'kiwify_access_token'
    assert parsed.access_token == TOKEN and parsed.account_id == CREDENTIAL['account_id']
    for changes in ({'access_token': 'Bearer '+TOKEN}, {'account_id': 'https://kiwify.com.br'}, {'credential_type': 'another_token'}):
        with pytest.raises(ValidationError):
            native.KiwifyTokenCredential.model_validate({**CREDENTIAL, **changes})


def test_stats_does_not_inherit_the_sales_listing_date_limit():
    node = make_node({'operation': 'get_sales_stats', 'start_date': '2025-01-01', 'end_date': '2026-01-01'})
    assert node.config.config.end_date == '2026-01-01'
