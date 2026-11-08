"""Offline Debitura contract requests, credential shaping and failure regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import debitura_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/debitura/routes.json').read_text())
TOKEN = 'debitura-synthetic-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='debitura-test', node_type='automation-debitura',
        node_data={'config': config, 'credentials': {'credential_type': 'debitura_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_documented_operation_request_and_response(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, lambda _: httpx.Response(fixture['status'], json=fixture['response']))
    result = await node(fixture['config']).execute({})
    assert result == {'status': 'success', 'http_status': fixture['status'], 'data': fixture['response']}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method'] and request.url.path == fixture['path']
    assert request.url.host == 'customer-api.debitura.com'
    assert request.headers['XApiKey'] == TOKEN
    assert request.headers['Accept'] == 'application/json'
    assert 'authorization' not in request.headers
    if operation == 'create_case':
        body = json.loads(request.content)
        assert body['debtor'] == fixture['config']['debtor']
        assert body['date'] == '2025-01-15T00:00:00+00:00'
        assert body['dueDate'] == '2025-02-15T00:00:00+00:00'
        assert body['amountToRecover'] == 5000 and 'operation' not in body
    if operation == 'send_case_chat':
        assert json.loads(request.content) == {'message': fixture['config']['message'], 'userEmail': 'john.doe@example.com'}
    if operation == 'update_division':
        assert json.loads(request.content) == {'companyName': 'Acme Corporation', 'city': 'Copenhagen', 'countryCode': 'DK'}
    if operation == 'archive_division':
        assert not request.content


@pytest.mark.asyncio
async def test_pagination_case_sensitive_queries_and_repeated_arrays(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=FIXTURES['list_cases']['response']))
    await node({'operation': 'list_cases', 'page': 2, 'page_size': 40,
        'statuses': ['Active', 'Paused'], 'sort': 'DateCreated:desc'}).execute({})
    assert requests[0].url.params.multi_items() == [('Page', '2'), ('PageSize', '40'), ('Statuses', 'Active'), ('Statuses', 'Paused'), ('Sort', 'DateCreated:desc')]
    requests.clear()
    await node({'operation': 'list_divisions', 'page': 3, 'include_archived': False}).execute({})
    assert dict(requests[0].url.params) == {'page': '3', 'pageSize': '10', 'includeArchived': 'false'}
    requests.clear()
    await node({'operation': 'list_tasks', 'task_types': ['ReplyToChat', 'SignContract']}).execute({})
    assert requests[0].url.params.get_list('type') == ['ReplyToChat', 'SignContract']


@pytest.mark.asyncio
async def test_reference_encoding_and_idempotency_header(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={}))
    await node({'operation': 'get_case_by_creditor_reference', 'creditor_reference': 'INV / ? café'}).execute({})
    assert b'INV%20%2F%20%3F%20caf%C3%A9' in requests[0].url.raw_path
    assert not requests[0].url.query
    config = {**FIXTURES['create_case']['config'], 'idempotency_key': 'test-request-42'}
    await node(config).execute({})
    assert requests[1].headers['Idempotency-Key'] == 'test-request-42'
    assert 'idempotency_key' not in json.loads(requests[1].content)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 422, 429, 500])
async def test_rejection_is_not_success_or_retried_and_redacts_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={'message': 'Rejected: ' + TOKEN}))
    result = await node(FIXTURES['create_case']['config']).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert 'Rejected:' in result['error'] and TOKEN not in str(result)
    assert len(requests) == 1 and 'data' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, 'html', {}, {'businessErrors': [{'message': 'Refused'}]}])
async def test_malformed_or_error_envelope_fails(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    assert (await node({'operation': 'get_me'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_timeout_does_not_retry_mutation(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout('late', request=request)
    requests = transport(monkeypatch, fail)
    result = await node(FIXTURES['create_case']['config']).execute({})
    assert result['status'] == 'error' and len(requests) == 1


def test_manual_credential_defaults_and_account_evidence():
    shaped, errors, resolved = shape_credential('debitura_api_key', {'api_key': TOKEN})
    assert resolved and not errors and shaped['api_key'] == TOKEN
    assert native.DebituraAPIKeyCredential(api_key=TOKEN).credential_type == 'debitura_api_key'
    assert native.DebituraNode.connection_evidence.identity_operation == 'get_me'
    assert native.DebituraNode.connection_evidence.proves == 'account'


@pytest.mark.parametrize('config', [
    {'operation': 'get_case', 'case_id': '../other'},
    {'operation': 'list_cases', 'page_size': 101},
    {'operation': 'send_case_chat', 'case_id': FIXTURES['get_case']['config']['case_id'], 'message': 'Hi'},
    {**FIXTURES['preview_case']['config'], 'amountToRecover': -1},
    {**FIXTURES['create_case']['config'], 'date': 'invalid'},
    {**FIXTURES['preview_case']['config'], 'amountToRecoverOver12Months': 300},
    {**FIXTURES['preview_case']['config'], 'claimLines': [{'amount': 100, 'dueDate': '2025-01-01'}]},
])
def test_invalid_inputs_fail_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        native.DebituraFullConfig.model_validate({'config': config, 'credentials': {'api_key': TOKEN}})


@pytest.mark.asyncio
async def test_claim_lines_are_separate_from_amount_and_dates_are_normalized(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"id": "created"}))
    config = {**FIXTURES['preview_case']['config'], 'claimLines': [
        {'dueDate': '2025-01-15', 'amount': 423.42, 'reference': 'INV-1001'}]}
    del config['amountToRecover']
    result = await node(config).execute({})
    assert result['status'] == 'success'
    body = json.loads(requests[0].content)
    assert 'amountToRecover' not in body
    assert body['claimLines'] == [{'dueDate': '2025-01-15T00:00:00+00:00', 'amount': 423.42, 'reference': 'INV-1001'}]


def test_earliest_claim_line_date_does_not_restrict_case_invoice_dates():
    old_invoice = {**FIXTURES['create_case']['config'], 'date': '1999-12-31'}
    assert native.DebituraCreateCaseConfig.model_validate(old_invoice).date.startswith('1999-12-31T')
    with pytest.raises(ValidationError):
        native.ClaimLine(amount=10, dueDate='1999-12-31')
