"""Exercise Revolut's published examples through the actual node factory.

HTTP is intercepted at the client boundary; no account, funds or live token is used.
"""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import revolut_for_business_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/revolut-for-business/published.json').read_text())
ID = 'af98333c-ea53-482b-93c2-1fa5e4eae671'
TOKEN = 'synthetic-revolut-token'
CASES = [
    ('list_accounts', 'getAccounts', {}),
    ('get_account', 'getAccount', {'account_id': ID}),
    ('get_bank_details', 'getAccountDetails', {'account_id': ID}),
    ('list_transactions', 'getTransactions', {'count': 25, 'from_time': '2022-08-01', 'to_time': '2022-09-01', 'state': ['pending', 'completed']}),
    ('get_transaction', 'getTransaction', {'transaction_id': ID}),
    ('list_counterparties', 'getCounterparties', {'name': 'John Smith', 'limit': 30}),
    ('get_counterparty', 'getCounterparty', {'counterparty_id': ID}),
    ('create_counterparty', 'addCounterparty', None),
    ('get_exchange_rate', 'getRate', {'from_currency': 'GBP', 'to_currency': 'EUR', 'amount': 10}),
    ('list_expenses', 'getExpenses', {'count': 20}),
    ('get_expense', 'getExpense', {'expense_id': ID}),
    ('list_payment_drafts', 'getPaymentDrafts', {'source': 'all'}),
    ('get_payment_draft', 'getPaymentDraft', {'payment_draft_id': ID}),
    ('create_payment_draft', 'createPaymentDraft', None),
    ('create_payment', 'createPayment', None),
    ('create_transfer', 'createTransfer', None),
    ('exchange_money', 'exchangeMoney', None),
    ('list_cards', 'getCards', {'limit': 50}),
    ('get_card', 'getCard', {'card_id': ID}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, environment='production'):
    return NodeFactory.create_node(node_id='revolut-test', node_type=native.RevolutBusinessNode.integration_type,
        node_data={'config': config, 'credentials': {'credential_type': 'revolut_business_access_token', 'access_token': TOKEN, 'environment': environment}})


def intercept(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs == {'timeout': 30, 'follow_redirects': False, 'trust_env': False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,example_id,config', CASES, ids=[c[0] for c in CASES])
async def test_revolut_for_business_published_contract(monkeypatch, operation, example_id, config):
    fixture = EXAMPLES[example_id]
    supplied = copy.deepcopy(fixture['request'] if config is None else config)
    if operation == 'exchange_money':
        supplied['from_side'] = supplied.pop('from')
        supplied['to_side'] = supplied.pop('to')
    requests = intercept(monkeypatch, fixture['response'])
    result = await node({'operation': operation, **supplied}).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method']
    expected = fixture['path'].replace('{id}', ID)
    for field in ('account_id', 'counterparty_id', 'expense_id', 'payment_draft_id', 'card_id'):
        expected = expected.replace('{' + field + '}', ID)
    assert request.url.path == '/api/1.0' + expected
    assert request.url.host == 'b2b.revolut.com'
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if 'request' in fixture:
        assert json.loads(request.content) == fixture['request']
    if operation == 'list_transactions':
        assert request.url.params.get_list('state') == ['pending', 'completed']
        assert request.url.params['from'] == '2022-08-01'
        assert request.url.params['to'] == '2022-09-01'
    if operation == 'get_exchange_rate':
        assert dict(request.url.params) == {'from': 'GBP', 'to': 'EUR', 'amount': '10.0'}
    if operation.startswith('list_'):
        expected_body = fixture['response']['payment_orders'] if operation == 'list_payment_drafts' else fixture['response']
        assert result['items'] == expected_body and result['page_only'] is True
    else:
        assert result['data'] == fixture['response']
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,field,path', [
    ('delete_counterparty', 'counterparty_id', '/counterparty/'),
    ('delete_payment_draft', 'payment_draft_id', '/payment-drafts/'),
])
async def test_revolut_for_business_delete_and_sandbox(monkeypatch, operation, field, path):
    requests = intercept(monkeypatch, None, 204)
    assert await node({'operation': operation, field: ID}, 'sandbox').execute({}) == {'status': 'success', 'deleted': True}
    assert len(requests) == 1 and requests[0].method == 'DELETE'
    assert requests[0].url.host == 'sandbox-b2b.revolut.com'
    assert requests[0].url.path == '/api/1.0' + path + ID
    assert requests[0].content == b''


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_revolut_for_business_does_not_follow_or_retry_writes(monkeypatch, status):
    requests = intercept(monkeypatch, {'message': 'Rejected'}, status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'create_payment', **EXAMPLES['createPayment']['request']}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_revolut_for_business_empty_accounts_are_valid_evidence(monkeypatch):
    requests = intercept(monkeypatch, [])
    result = await node({'operation': 'list_accounts'}).execute({})
    assert result['items'] == [] and len(requests) == 1
    assert native.RevolutBusinessNode.connection_evidence.operation == 'list_accounts'
    assert native.RevolutBusinessCredential(access_token=TOKEN).credential_type == 'revolut_business_access_token'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'error': 'rejected'}, 'html'])
async def test_revolut_for_business_rejects_bad_list_response(monkeypatch, body):
    intercept(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'list_accounts'}).execute({})


def test_revolut_for_business_exchange_requires_exactly_one_amount():
    supplied = copy.deepcopy(EXAMPLES['exchangeMoney']['request'])
    supplied['from_side'] = supplied.pop('from')
    supplied['to_side'] = supplied.pop('to')
    for amounts in ((None, None), (10, 10)):
        for key, value in zip(('from_side', 'to_side'), amounts):
            supplied[key]['amount'] = value
        with pytest.raises(ValidationError):
            native.ExchangeMoney(**supplied)


@pytest.mark.parametrize('amount', [0, -1, float('inf'), float('nan')])
def test_revolut_for_business_refuses_invalid_payment_amounts(amount):
    with pytest.raises(ValidationError):
        native.CreatePayment(**{**EXAMPLES['createPayment']['request'], 'amount': amount})


@pytest.mark.parametrize('identifier', ['.', '..', 'bad/id', 'bad\\id'])
def test_revolut_for_business_refuses_path_traversal(identifier):
    with pytest.raises(ValidationError):
        native.GetTransaction(transaction_id=identifier)
