"""Tomba wire regression tests with provider-authored response examples."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import tomba_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/tomba/responses.json').read_text())
CREDENTIAL = {'credential_type': 'tomba_api_key', 'api_key': 'test-tomba-key', 'api_secret': 'test-tomba-secret'}
CASES = [
    ({'operation': 'domain_search', 'domain': 'stripe.com'}, 'GET', '/domain-search', {'domain': 'stripe.com', 'page': '1', 'limit': '10'}),
    ({'operation': 'email_finder', 'domain': 'stripe.com', 'first_name': 'Jane', 'last_name': 'Doe'}, 'GET', '/email-finder', {'domain': 'stripe.com', 'first_name': 'Jane', 'last_name': 'Doe'}),
    ({'operation': 'email_verifier', 'email': 'jane.doe@stripe.com'}, 'GET', '/email-verifier', {'email': 'jane.doe@stripe.com'}),
    ({'operation': 'domain_suggestions', 'query': 'Stripe'}, 'GET', '/domain-suggestions', {'query': 'Stripe'}),
    ({'operation': 'technology', 'domain': 'stripe.com'}, 'GET', '/technology', {'domain': 'stripe.com'}),
    ({'operation': 'list_leads', 'page': 2, 'list_id': 1}, 'GET', '/leads', {'page': '2', 'limit': '10', 'list': '1'}),
    ({'operation': 'get_lead', 'lead_id': 1}, 'GET', '/leads/1', {}),
    ({'operation': 'create_lead', 'email': 'jane.doe@stripe.com', 'list_id': 1}, 'POST', '/leads', {'email': 'jane.doe@stripe.com', 'list_id': 1}),
    ({'operation': 'update_lead', 'lead_id': 1, 'notes': 'Contacted'}, 'PUT', '/leads/1', {'notes': 'Contacted'}),
    ({'operation': 'delete_lead', 'lead_id': 1}, 'DELETE', '/leads/1', {}),
    ({'operation': 'list_lead_lists'}, 'GET', '/leads_lists', {}),
    ({'operation': 'get_lead_list', 'list_id': 1}, 'GET', '/leads_lists/1', {}),
    ({'operation': 'create_lead_list', 'name': 'Prospects'}, 'POST', '/leads_lists', {'name': 'Prospects', 'favorite': False}),
    ({'operation': 'update_lead_list', 'list_id': 1, 'favorite': True}, 'PUT', '/leads_lists/1', {'favorite': True}),
    ({'operation': 'delete_lead_list', 'list_id': 1}, 'DELETE', '/leads_lists/1', {}),
]

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='tomba-test', node_type='automation-tomba', node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, handler):
    def client(**kwargs):
        assert kwargs == {'timeout': 180, 'follow_redirects': False, 'trust_env': False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,payload', CASES, ids=[c[0]['operation'] for c in CASES])
async def test_documented_response_and_exact_request(monkeypatch, config, method, path, payload):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == method
        assert str(request.url).split('?')[0] == native.BASE + path
        assert request.headers['X-Tomba-Key'] == CREDENTIAL['api_key']
        assert request.headers['X-Tomba-Secret'] == CREDENTIAL['api_secret']
        assert 'X-TANNIN-KEY' not in request.headers
        assert CREDENTIAL['api_secret'] not in str(request.url)
        if method == 'GET':
            assert dict(request.url.params) == payload
            assert not request.content
        elif method in {'POST', 'PUT'}:
            assert json.loads(request.content) == payload
            if 'list_id' in payload:
                assert type(json.loads(request.content)['list_id']) is int
        else:
            assert not request.content
        return httpx.Response(201 if config['operation'].startswith('create_') else 200, json=FIXTURES[config['operation']])
    transport(monkeypatch, handler)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert result['data'] == FIXTURES[config['operation']]['data']
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 200])
async def test_provider_rejection_reaches_connection_seam(monkeypatch, status):
    transport(monkeypatch, lambda request: httpx.Response(status, json={'errors': {'message': 'Invalid API key'}}))
    with pytest.raises(ValueError, match='Invalid API key'):
        await node({'operation': 'list_leads'}).execute({})


@pytest.mark.asyncio
async def test_empty_leads_and_secret_redaction(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={'data': {'leads': [], 'secret_token': 'never-output', 'note': CREDENTIAL['api_secret']}}))
    result = await node({'operation': 'list_leads'}).execute({})
    assert result['data'] == {'leads': [], 'note': '[redacted]'}


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(302, headers={'Location': 'https://other.test/'}), httpx.Response(200, text='<html>error</html>'), httpx.Response(200, json={})])
async def test_rejects_unconfirmed_responses(monkeypatch, response):
    transport(monkeypatch, lambda request: response)
    with pytest.raises(ValueError):
        await node({'operation': 'list_leads'}).execute({})


@pytest.mark.asyncio
async def test_lead_options_use_total_not_rounded_down_total_pages(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'data': {'leads': [{'id': 1, 'email': 'jane.doe@stripe.com'}]}, 'meta': {'total': 201, 'total_pages': 1}})
    transport(monkeypatch, handler)
    result = await native.TombaNode.load_field_options('lead_id', CREDENTIAL)
    assert result == {'options': [{'value': '1', 'label': 'jane.doe@stripe.com'}], 'next_page_token': '2'}
    assert dict(calls[0].url.params) == {'page': '1', 'limit': '200'}


@pytest.mark.parametrize('config', [
    {'operation': 'update_lead', 'lead_id': 1},
    {'operation': 'update_lead', 'lead_id': 1, 'first_name': 'J'},
    {'operation': 'update_lead_list', 'list_id': 1},
    {'operation': 'create_lead_list', 'name': 'X'},
    {'operation': 'domain_search', 'domain': '../evil.test'},
    {'operation': 'get_lead', 'lead_id': '../2'},
    {'operation': 'list_leads', 'limit': 201},
])
def test_invalid_configs_fail_before_http(config):
    assert native.TombaNode.validate_config({'config': config, 'credentials': CREDENTIAL})['valid'] is False


def test_manual_credentials():
    credential = native.TombaApiKeyCredential(api_key='test-key-value', api_secret='test-secret-value')
    assert credential.credential_type == 'tomba_api_key'
    with pytest.raises(ValidationError):
        native.TombaApiKeyCredential(api_key='https://example.com/key', api_secret='test-secret-value')


@pytest.mark.asyncio
async def test_failed_mutation_is_not_success(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={'data': {'status': False, 'message': 'Lead not found'}}))
    with pytest.raises(ValueError, match='Lead not found'):
        await node({'operation': 'delete_lead', 'lead_id': 1}).execute({})


@pytest.mark.asyncio
async def test_connection_does_not_accept_an_unrelated_data_object(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={'data': {}}))
    with pytest.raises(ValueError, match='leads array'):
        await node({'operation': 'list_leads'}).execute({})


@pytest.mark.asyncio
async def test_list_options_and_empty_lead_page(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={'data': {'list_leads': [{'id': 4, 'name': 'Prospects'}]}}))
    assert await native.TombaNode.load_field_options('list_id', CREDENTIAL) == [{'value': '4', 'label': 'Prospects'}]
    transport(monkeypatch, lambda request: httpx.Response(200, json={'data': {'leads': []}}))
    assert await native.TombaNode.load_field_options('lead_id', CREDENTIAL) == {'options': [], 'next_page_token': None}
