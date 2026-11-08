"""Exercise native Airwallex nodes against provider-published response examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import airwallex_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/airwallex/published_examples.json').read_text())
ID = '8365ea88-2946-4877-abe1-e02a1015288d'
CREDENTIAL = {'credential_type': 'airwallex_api_key', 'client_id': 'fixture-client-id', 'api_key': 'fixture-api-key'}
TRANSFER = {'beneficiary_id': ID, 'request_id': 'fixture-request-1', 'transfer_amount': '10000',
            'transfer_currency': 'AUD', 'source_currency': 'AUD', 'reason': 'travel',
            'reference': 'PMT1936398', 'transfer_method': 'SWIFT'}
BENEFICIARY = {'entity_type': 'COMPANY', 'company_name': 'Complete Concrete Pty Ltd',
               'bank_details': {'account_currency': 'AUD', 'account_name': 'Lee Da Ming',
                                'bank_country_code': 'AU', 'account_number': '12750852'}}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id='airwallex-fixture', node_type='automation-airwallex',
        node_data={'config': config, 'credentials': {**CREDENTIAL, **credential}})



@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.ROUTES))
async def test_every_operation_exact_wire_and_published_response(monkeypatch, operation):
    method, path = native.ROUTES[operation]
    config = {'operation': operation}
    if '{id}' in path:
        config['id'] = ID
    if operation in {'create_transfer', 'validate_transfer'}:
        config.update(TRANSFER)
    if operation == 'create_beneficiary':
        config.update(beneficiary=BENEFICIARY, transfer_methods=['SWIFT'])
    if operation == 'update_global_account':
        config['nick_name'] = 'Treasury'
    key = method + ' /api/v1' + path
    published = EXAMPLES['responses'].get(key, {'status': 200, 'body': {}})
    # Capture the class before monkeypatching the shared module attribute.
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(201, json=EXAMPLES['responses']['POST /api/v1/authentication/login']['body'])
        return httpx.Response(published['status'], json=published['body'])
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = await node(config).execute({})
    assert len(requests) == 2
    login, request = requests
    assert login.method == 'POST' and login.url.path == '/api/v1/authentication/login'
    assert login.headers['x-api-key'] == CREDENTIAL['api_key']
    assert login.headers['x-client-id'] == CREDENTIAL['client_id']
    assert 'authorization' not in login.headers
    assert request.method == method and request.url.path == '/api/v1' + path.replace('{id}', ID)
    assert request.url.host == 'api.airwallex.com'
    assert request.headers['authorization'].startswith('Bearer eyJ')
    assert 'x-api-key' not in request.headers and 'x-client-id' not in request.headers
    assert result['data'] == published['body'] and result['status'] == 'success'
    if operation in {'create_transfer', 'validate_transfer'}:
        assert json.loads(request.content) == TRANSFER
    if operation == 'create_beneficiary':
        assert json.loads(request.content) == {'beneficiary': BENEFICIARY, 'transfer_methods': ['SWIFT']}
    if operation == 'update_global_account':
        assert json.loads(request.content) == {'nick_name': 'Treasury'}
    if operation in {'list_balance_history', 'list_financial_transactions', 'list_beneficiaries'}:
        assert dict(request.url.params) == {'page_num': '0', 'page_size': '100'}
    if operation == 'list_balances':
        assert dict(request.url.params) == {'account_type': 'cash'}


@pytest.mark.asyncio
async def test_sandbox_host_cursor_preserved_and_provider_false_not_deleted(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path.endswith('/login'):
            return httpx.Response(201, json={'token': 'fixture-access-token'})
        return httpx.Response(200, json=False if request.url.path.endswith('/delete') else {'items': [], 'page_after': 'next-cursor'})
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = await node({'operation': 'delete_beneficiary', 'id': ID}, environment='sandbox', account_id='acct_LTwYEh8EPa2yiA3dCoBEVA').execute({})
    assert result['data'] is False
    assert requests[0].headers['x-login-as'] == 'acct_LTwYEh8EPa2yiA3dCoBEVA'
    assert 'x-login-as' not in requests[1].headers
    assert all(request.url.host == 'api.sandbox.airwallex.com' for request in requests)
    await node({'operation': 'list_transfers', 'page': 'opaque/+cursor', 'page_size': 20}).execute({})
    assert dict(requests[-1].url.params) == {'page': 'opaque/+cursor', 'page_size': '20'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
async def test_rejection_no_retry_or_secret_leak(monkeypatch, status):
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, text='credentials_invalid ' + CREDENTIAL['api_key'])
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ValueError, match=f'HTTP {status}') as error:
        await node({'operation': 'list_global_accounts'}).execute({})
    assert CREDENTIAL['api_key'] not in str(error.value) and len(requests) == 1


def test_invalid_routes_credentials_amounts_and_unknown_operation():
    for config in [{'operation': 'get_global_account', 'id': '../escape'},
                   {'operation': 'get_beneficiary', 'id': 'not-a-uuid'},
                   {'operation': 'create_transfer', **TRANSFER, 'transfer_amount': '-1'},
                   {'operation': 'custom_request'}]:
        with pytest.raises(ValidationError):
            native.AirwallexFullConfig.model_validate({'config': config, 'credentials': CREDENTIAL})
    with pytest.raises(ValidationError):
        native.AirwallexAPIKeyCredential.model_validate({**CREDENTIAL, 'environment': 'https://evil.test'})


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, False, {'items': 'invalid'}])
async def test_malformed_account_list_cannot_prove_connection(monkeypatch, body):
    original = httpx.AsyncClient
    def respond(request):
        return httpx.Response(201, json={'token': 'fixture-token'}) if request.url.path.endswith('/login') else httpx.Response(200, json=body)
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ValueError, match='unexpected response shape'):
        await node({'operation': 'list_global_accounts'}).execute({})
