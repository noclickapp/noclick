"""Coinbase Exchange contract fixtures, exact signatures and uncertain writes."""
import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import coinbase_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures' / 'coinbase'
EXAMPLES = json.loads((FIXTURES / 'exchange_examples.json').read_text())['examples']
CONFIGS = json.loads((FIXTURES / 'operation_inputs.json').read_text())
KEY = 'synthetic-coinbase-api-key'
SECRET = base64.b64encode(b'fake-coinbase-hmac-secret-for-offline-tests').decode()
PASSPHRASE = 'synthetic-passphrase'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return dict(api_key=KEY, api_secret=SECRET, passphrase=PASSPHRASE)


def node(operation, **overrides):
    return NodeFactory.create_node(node_id='coinbase-fixture', node_type='automation-coinbase',
        node_data={'config': {'operation': operation, **CONFIGS[operation], **overrides}, 'credentials': credential()})


def transport(monkeypatch, reply):
    requests = []
    def respond(req):
        requests.append(req)
        return reply(req)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    monkeypatch.setattr(native.time, 'time', lambda: 1700000000.25)
    return requests


def documented_body(operation):
    schema = {
        'list_accounts': 'apiAccount', 'get_account': 'apiAccount',
        'list_holds': 'apiAccountHold', 'list_ledger': 'apiAccountLedgerEntry',
        'list_orders': 'apiOrder', 'get_order': 'apiOrder', 'create_order': 'apiOrder',
        'list_fills': 'apiOrderFill', 'get_fees': 'apiFees', 'list_products': 'apiProduct',
        'get_product': 'apiProduct', 'get_ticker': 'apiProductTicker', 'get_stats': 'apiProductStats',
        'get_order_book': 'apiProductBook', 'list_currencies': 'apiCurrency',
        'get_currency': 'apiCurrency', 'list_profiles': 'apiProfile', 'get_profile': 'apiProfile',
        'list_payment_methods': 'apiPaymentMethod',
    }
    if operation == 'cancel_order':
        return CONFIGS[operation]['order_id']
    body = EXAMPLES[schema[operation]]
    return [body] if operation in native.LISTS else body


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CONFIGS)
async def test_factory_each_operation_one_contract_request_and_signature(monkeypatch, operation):
    payload = documented_body(operation)
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    result = await node(operation).execute({})
    assert result['status'] == 'success' and result['data'] == payload
    assert len(requests) == 1
    req = requests[0]
    method, path = native.ROUTES[operation]
    for k, v in CONFIGS[operation].items():
        path = path.replace('{' + k + '}', str(v))
    assert req.method == method and req.url.path == path
    assert req.url.host == 'api.exchange.coinbase.com'
    message = req.headers['cb-access-timestamp'] + method + req.url.raw_path.decode() + req.content.decode()
    expected = base64.b64encode(hmac.new(base64.b64decode(SECRET), message.encode(), hashlib.sha256).digest()).decode()
    assert req.headers['cb-access-sign'] == expected
    assert req.headers['cb-access-key'] == KEY and req.headers['cb-access-passphrase'] == PASSPHRASE
    assert all(secret not in json.dumps(result) for secret in (KEY, SECRET, PASSPHRASE, expected))
    if method != 'GET':
        assert result['acknowledged'] and result['execution_verified'] is False
    if operation == 'create_order':
        assert json.loads(req.content) == {**CONFIGS[operation], 'type': 'limit'}
    if operation == 'list_orders':
        assert dict(req.url.params) == {'limit': '100', 'status': 'open'}


@pytest.mark.asyncio
async def test_paging_preserves_cursor_and_account_evidence(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=[], headers={'CB-AFTER': 'next:cursor+1', 'CB-BEFORE': 'previous'}))
    result = await node('list_orders', after='2026-11-08T12:30:45+00:00', product_id='BTC-USD', status='done').execute({})
    assert result['next_after'] == 'next:cursor+1' and result['next_before'] == 'previous' and result['page_only']
    assert requests[0].url.params['after'] == '2026-11-08T12:30:45+00:00'
    assert '%2B' in str(requests[0].url) and len(requests) == 1
    transport(monkeypatch, lambda req: httpx.Response(200, json=[EXAMPLES['apiAccount']]))
    result = await node('list_accounts').execute({})
    assert native.CoinbaseNode.connection_evidence.operation == 'list_accounts'
    assert native.CoinbaseNode.connection_evidence.proves == 'account'
    assert result['data'][0]['id'] == EXAMPLES['apiAccount']['id']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_rejection_redacts_and_does_not_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={'message': 'rejected ' + KEY + SECRET + PASSPHRASE}, headers={'Location': 'https://example.test/'}))
    with pytest.raises(ValueError) as exc:
        await node('create_order').execute({})
    assert str(status) in str(exc.value)
    assert all(v not in str(exc.value) for v in (KEY, SECRET, PASSPHRASE)) and len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_write_is_uncertain_and_never_retried(monkeypatch):
    def fail(req):
        raise httpx.ReadTimeout('do not expose ' + KEY, request=req)
    requests = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match='outcome is unknown') as exc:
        await node('create_order').execute({})
    assert KEY not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [{}], ['wrong'], {'message': 'bad'}, None])
async def test_wrong_list_response_cannot_verify_connection(monkeypatch, body):
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node('list_accounts').execute({})


@pytest.mark.asyncio
async def test_stalled_cursor_and_success_secret_echo_are_handled(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json=[], headers={'CB-AFTER': 'same'}))
    with pytest.raises(ValueError, match='nonadvancing'):
        await node('list_orders', after='same').execute({})
    transport(monkeypatch, lambda req: httpx.Response(200, json={'id': KEY, 'nested': [SECRET, PASSPHRASE]}))
    result = await node('get_account').execute({})
    assert KEY not in str(result) and SECRET not in str(result) and PASSPHRASE not in str(result)


@pytest.mark.parametrize('field,value', [('api_secret', 'not-base64'), ('api_key', 'key\nheader'), ('passphrase', 'https://example.test/secret')])
def test_invalid_credentials_are_rejected(field, value):
    data = credential()
    data[field] = value
    with pytest.raises(ValidationError):
        native.CoinbaseExchangeCredential.model_validate(data)


@pytest.mark.parametrize('field,value', [('price', '0'), ('size', '-1'), ('price', 'NaN'), ('product_id', '../accounts'), ('client_oid', 'not-a-uuid')])
def test_invalid_order_parameters_fail_before_request(field, value):
    with pytest.raises(ValueError):
        node('create_order', **{field: value})


def test_manual_credential_default_and_all_user_fields():
    cred = native.CoinbaseExchangeCredential.model_validate(credential())
    assert cred.credential_type == 'coinbase_exchange_api_key'
    assert set(cred.model_dump()) == {'credential_type', 'api_key', 'api_secret', 'passphrase'}
