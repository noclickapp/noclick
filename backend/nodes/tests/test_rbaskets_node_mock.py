"""Wire-level Request Baskets contract tests. Fixtures use the provider's Swagger examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import rbaskets_node as rb
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/rbaskets/documented.json').read_text())['examples']
CREDENTIAL = {'credential_type': 'rbaskets_token', 'token': 'synthetic-basket-token', 'basket_name': 'basket22'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='test-rbaskets', node_type='automation-rbaskets',
        node_data={'config': config, 'credentials': credentials or CREDENTIAL})


def transport(monkeypatch, status, payload=None):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(rb, 'guarded_async_client', client)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,status,model', [
    ('get_version', {}, 'GET', '/api/version', 200, 'Version'),
    ('get_statistics', {'max': 5}, 'GET', '/api/stats', 200, 'ServiceStats'),
    ('list_baskets', {'max': 20, 'skip': 0, 'q': 'basket'}, 'GET', '/api/baskets', 200, 'Baskets'),
    ('create_basket', {'name': 'mybasket', 'capacity': 250}, 'POST', '/api/baskets/mybasket', 201, 'Token'),
    ('get_basket', {}, 'GET', '/api/baskets/basket22', 200, 'Config'),
    ('update_basket', {'capacity': 250}, 'PUT', '/api/baskets/basket22', 204, None),
    ('delete_basket', {}, 'DELETE', '/api/baskets/basket22', 204, None),
    ('get_response', {'method': 'POST'}, 'GET', '/api/baskets/basket22/responses/POST', 200, 'Response'),
    ('update_response', {'method': 'POST', 'response_status': 200, 'response_body': 'Success', 'headers_json': json.dumps(EXAMPLES['Headers'])}, 'PUT', '/api/baskets/basket22/responses/POST', 204, None),
    ('list_requests', {'q': 'abc_test', 'search_in': 'body', 'max': 20, 'skip': 20}, 'GET', '/api/baskets/basket22/requests', 200, 'Requests'),
    ('delete_requests', {}, 'DELETE', '/api/baskets/basket22/requests', 204, None),
])
async def test_rbaskets_all_eleven_contract_routes(monkeypatch, operation, config, method, path, status, model):
    payload = EXAMPLES.get(model)
    seen = transport(monkeypatch, status, payload)
    result = await node({'operation': operation, **config}).execute({})
    assert result['status'] == 'success' and result['http_status'] == status
    assert len(seen) == 1
    request = seen[0]
    assert request.method == method and request.url.path == path and request.url.host == 'rbaskets.in'
    assert request.headers['Authorization'] == CREDENTIAL['token']
    if operation in {'create_basket', 'update_basket'}:
        assert json.loads(request.content) == {'capacity': 250}
    elif operation == 'update_response':
        assert json.loads(request.content) == {'status': 200, 'body': 'Success', 'headers': EXAMPLES['Headers'], 'is_template': False}
    else:
        assert not request.content
    if operation == 'list_requests':
        assert dict(request.url.params) == {'q': 'abc_test', 'in': 'body', 'max': '20', 'skip': '20'}
        assert result['next_skip'] == 21
    elif operation == 'list_baskets':
        assert dict(request.url.params) == {'max': '20', 'skip': '0', 'q': 'basket'}
        assert result['next_skip'] == 3
    if model:
        assert result['data'] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize('action,key', [('list_baskets', 'names'), ('list_requests', 'requests')])
async def test_rbaskets_documented_204_empty_pages(monkeypatch, action, key):
    transport(monkeypatch, 204)
    result = await node({'operation': action}).execute({})
    assert result['data'] == {key: [], 'has_more': False}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 409, 422, 500])
async def test_rbaskets_rejections_never_report_success_or_echo_token(monkeypatch, status):
    seen = transport(monkeypatch, status, {'error': CREDENTIAL['token']})
    result = await node({'operation': 'get_basket'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert CREDENTIAL['token'] not in str(result) and len(seen) == 1


@pytest.mark.asyncio
async def test_rbaskets_clearing_forwarding_and_false_values(monkeypatch):
    seen = transport(monkeypatch, 204)
    result = await node({'operation': 'update_basket', 'disable_forwarding': True, 'proxy_response': False, 'insecure_tls': False, 'expand_path': False}).execute({})
    assert result['status'] == 'success'
    assert json.loads(seen[0].content) == {'forward_url': '', 'proxy_response': False, 'insecure_tls': False, 'expand_path': False}


@pytest.mark.parametrize('value', ['../other', '..', ' .. ', 'https://rbaskets.in/basket22', 'basket?x=1', 'a#b', 'a\\b', 'a\nb'])
def test_rbaskets_names_cannot_escape_route(value):
    with pytest.raises(ValidationError):
        rb.RBasketsTokenCredential.model_validate({**CREDENTIAL, 'basket_name': value})


@pytest.mark.parametrize('headers', ['not-json', '[]', '{"Accept":"application/json"}', '{"Accept":[1]}'])
def test_rbaskets_response_headers_must_be_documented_string_arrays(headers):
    with pytest.raises(ValidationError):
        rb.UpdateResponse(headers_json=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize('action,payload', [('list_requests', {}), ('list_baskets', {'names': [], 'has_more': 'yes'}), ('create_basket', {}), ('get_basket', [])])
async def test_rbaskets_malformed_success_payloads(monkeypatch, action, payload):
    transport(monkeypatch, 201 if action == 'create_basket' else 200, payload)
    with pytest.raises(ValueError):
        await node({'operation': action, **({'name': 'mybasket'} if action == 'create_basket' else {})}).execute({})


def test_rbaskets_manual_credential_default_and_connection_evidence():
    credential = rb.RBasketsTokenCredential.model_validate({'token': 'synthetic-basket-token', 'basket_name': 'basket22'})
    assert credential.credential_type == 'rbaskets_token'
    assert rb.RBasketsNode.connection_evidence.operation == 'get_basket'
    assert rb.GetBasket().name is None
